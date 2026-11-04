"""Chapter-level OCR orchestration: ordered page images -> one multi-page PDF -> MinerU."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from io import BytesIO

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.core.config import get_settings
from ruangao_note.db.base import utc_now
from ruangao_note.domain.models import Chapter, ChapterPage, ProcessingRun
from ruangao_note.services.image_storage import ImageStorage
from ruangao_note.services.mineru_cloud import MinerUCloudParser, MinerUSettings


class ChapterOCRNotFoundError(LookupError):
    """Raised when a chapter has no active pages or does not exist."""


class ChapterOCRResumeConflictError(ValueError):
    """Raised when an OCR run cannot be resumed safely."""


@dataclass(frozen=True)
class PDFPageReference:
    pdf_page_index: int
    chapter_page_id: str
    sort_order: int
    textbook_page_number: int | None
    original_filename: str
    width: int
    height: int


def build_chapter_pdf(
    pages: list[ChapterPage],
    storage: ImageStorage,
    *,
    max_dimension: int = 3508,
) -> tuple[bytes, list[PDFPageReference]]:
    """Build a temporary multi-page PDF in memory without modifying source images."""
    if not pages:
        raise ValueError("At least one page is required to build a chapter PDF.")

    pdf_images: list[Image.Image] = []
    references: list[PDFPageReference] = []
    try:
        for index, page in enumerate(pages):
            source_path = storage.resolve(page.storage_path)
            if not source_path.is_file():
                raise FileNotFoundError(f"Original image for page {page.id} is missing.")
            with Image.open(source_path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
            if page.rotation:
                image = image.rotate(-page.rotation, expand=True)
            image.thumbnail(
                (max_dimension, max_dimension),
                Image.Resampling.LANCZOS,
            )
            pdf_images.append(image)
            references.append(
                PDFPageReference(
                    pdf_page_index=index + 1,
                    chapter_page_id=page.id,
                    sort_order=page.sort_order,
                    textbook_page_number=page.textbook_page_number,
                    original_filename=page.original_filename,
                    width=image.width,
                    height=image.height,
                )
            )

        output = BytesIO()
        pdf_images[0].save(
            output,
            format="PDF",
            save_all=True,
            append_images=pdf_images[1:],
            resolution=150.0,
            quality=90,
            optimize=True,
        )
        return output.getvalue(), references
    finally:
        for image in pdf_images:
            image.close()


class ChapterOCRService:
    """Create one immutable ProcessingRun for an entire chapter OCR attempt."""

    def __init__(
        self,
        session: Session,
        *,
        storage: ImageStorage | None = None,
        parser: MinerUCloudParser | None = None,
    ) -> None:
        self.session = session
        self.storage = storage or ImageStorage()
        self.parser = parser

    def resume_run(self, chapter_id: str, run_id: str) -> ProcessingRun:
        """Resume result retrieval for an existing MinerU batch; never resubmit its PDF."""
        run = self.session.scalar(
            select(ProcessingRun).where(
                ProcessingRun.id == run_id,
                ProcessingRun.chapter_id == chapter_id,
                ProcessingRun.task_type == "chapter_ocr",
                ProcessingRun.provider == "mineru_cloud",
            )
        )
        if run is None:
            raise ChapterOCRNotFoundError("OCR run not found in this chapter.")
        raw = run.raw_result if isinstance(run.raw_result, dict) else {}
        batch_id = raw.get("batch_id")
        if run.status != "failed" or not batch_id:
            raise ChapterOCRResumeConflictError(
                "Only failed MinerU runs with a saved batch_id can be resumed."
            )

        settings = get_settings()
        parser = self.parser or MinerUCloudParser(
            MinerUSettings(
                token=settings.mineru_token,
                api_base_url=settings.mineru_api_base_url,
                model_version=settings.mineru_model_version,
                language=settings.mineru_language,
                poll_interval_seconds=settings.mineru_poll_interval_seconds,
                max_wait_seconds=settings.mineru_max_wait_seconds,
            )
        )
        run.status = "running"
        run.error_message = None
        run.started_at = utc_now()
        self.session.commit()
        try:
            result = parser.resume_batch(str(batch_id))
            page_references = raw.get("page_references") or []
            page_count = int(raw.get("page_count") or len(page_references))
            run.raw_result = {
                **raw,
                "state": result["state"],
                "model_version": result["model_version"],
                "language": result["language"],
                "recovery": {"method": "download_existing_batch", "resubmitted": False},
            }
            run.normalized_result = {
                "schema_version": "1.0",
                "provider": "mineru_cloud",
                "provider_version": run.provider_version,
                "document_type": "chapter",
                "page_count": page_count,
                "page_references": page_references,
                "artifacts": result["artifacts"],
            }
            run.quality_report = {
                "page_count": page_count,
                "pdf_size_bytes": raw.get("pdf_size_bytes"),
                "source_images_preserved": True,
                "recovered_existing_batch": True,
                "notes": [
                    "Results were retrieved from the existing MinerU batch.",
                    "The PDF was not uploaded again and no new batch was created.",
                ],
            }
            run.status = "succeeded"
            run.completed_at = utc_now()
            self.session.commit()
            self.session.refresh(run)
            return run
        except Exception as exc:
            self.session.rollback()
            failed_run = self.session.get(ProcessingRun, run_id)
            if failed_run is None:
                raise
            failed_run.status = "failed"
            failed_run.error_message = f"{type(exc).__name__}: {exc}"[:4000]
            failed_run.completed_at = utc_now()
            self.session.commit()
            self.session.refresh(failed_run)
            return failed_run

    def process_chapter(self, chapter_id: str) -> ProcessingRun:
        chapter = self.session.get(Chapter, chapter_id)
        pages = self.session.scalars(
            select(ChapterPage)
            .where(
                ChapterPage.chapter_id == chapter_id,
                ChapterPage.status == "stored",
            )
            .order_by(ChapterPage.sort_order, ChapterPage.id)
        ).all()
        if chapter is None or not pages:
            raise ChapterOCRNotFoundError("Chapter not found or it has no active pages.")

        settings = get_settings()
        provider_version = settings.mineru_model_version
        run = ProcessingRun(
            chapter_id=chapter_id,
            page_id=None,
            task_type="chapter_ocr",
            provider="mineru_cloud",
            provider_version=provider_version,
            status="queued",
            config={
                "model_version": provider_version,
                "page_count": len(pages),
                "input_format": "multi_page_pdf",
                "page_order": "sort_order_ascending",
            },
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        run.status = "running"
        run.started_at = utc_now()
        self.session.commit()
        try:
            pdf_bytes, page_references = build_chapter_pdf(pages, self.storage)
            pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
            parser = self.parser or MinerUCloudParser(
                MinerUSettings(
                    token=settings.mineru_token,
                    api_base_url=settings.mineru_api_base_url,
                    model_version=settings.mineru_model_version,
                    language=settings.mineru_language,
                    poll_interval_seconds=settings.mineru_poll_interval_seconds,
                    max_wait_seconds=settings.mineru_max_wait_seconds,
                )
            )
            def persist_batch_id(batch_id: str) -> None:
                # Keep the remote task ID durable even if upload/poll/download fails.
                run.raw_result = {
                    "batch_id": batch_id,
                    "state": "submitted",
                    "stage": "batch_created",
                    "pdf_sha256": pdf_sha256,
                    "pdf_size_bytes": len(pdf_bytes),
                    "page_count": len(page_references),
                    "page_references": [asdict(item) for item in page_references],
                }
                self.session.commit()

            result = parser.parse_pdf(
                pdf_bytes,
                filename=f"chapter-{chapter.chapter_number}-{chapter.id[:8]}.pdf",
                on_batch_created=persist_batch_id,
            )
            run.raw_result = {
                "batch_id": result["batch_id"],
                "state": result["state"],
                "model_version": result["model_version"],
                "language": result["language"],
                "pdf_sha256": pdf_sha256,
                "pdf_size_bytes": len(pdf_bytes),
                "page_count": len(page_references),
                "page_references": [asdict(item) for item in page_references],
            }
            run.normalized_result = {
                "schema_version": "1.0",
                "provider": "mineru_cloud",
                "provider_version": provider_version,
                "document_type": "chapter",
                "page_count": len(page_references),
                "page_references": [asdict(item) for item in page_references],
                "artifacts": result["artifacts"],
            }
            run.quality_report = {
                "page_count": len(page_references),
                "pdf_size_bytes": len(pdf_bytes),
                "source_images_preserved": True,
                "notes": [
                    "All active chapter pages were submitted as one ordered PDF.",
                    "SourceBlock creation and page-level block anchoring are handled in TP-05.",
                ],
            }
            run.status = "succeeded"
            run.completed_at = utc_now()
            self.session.commit()
            self.session.refresh(run)
            return run
        except Exception as exc:
            self.session.rollback()
            failed_run = self.session.get(ProcessingRun, run.id)
            if failed_run is None:
                raise
            failed_run.status = "failed"
            failed_run.error_message = f"{type(exc).__name__}: {exc}"[:4000]
            failed_run.completed_at = utc_now()
            self.session.commit()
            self.session.refresh(failed_run)
            return failed_run
