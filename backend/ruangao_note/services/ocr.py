"""Provider-neutral OCR contracts, image preprocessing, and run orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Protocol

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.db.base import utc_now
from ruangao_note.domain.models import ChapterPage, ProcessingRun
from ruangao_note.services.image_storage import ImageStorage


@dataclass(frozen=True)
class OCRBlock:
    """One OCR text region; bbox coordinates are normalized to [0, 1]."""

    text: str
    block_type: str = "paragraph"
    bbox: tuple[float, float, float, float] | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class OCRProviderResponse:
    """Provider output before it is normalized and persisted."""

    blocks: tuple[OCRBlock, ...]
    raw_payload: dict[str, object]
    provider: str
    provider_version: str


@dataclass(frozen=True)
class ImageQualityReport:
    """Heuristic quality indicators; these are warnings, not OCR guarantees."""

    width: int
    height: int
    grayscale_stddev: float
    edge_stddev: float
    is_blank_suspected: bool
    is_blurry_suspected: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OCRProvider(Protocol):
    """Replaceable OCR engine contract. Implementations must not mutate input bytes."""

    name: str
    version: str

    def recognize(self, image_bytes: bytes, *, page_number: int | None) -> OCRProviderResponse:
        """Recognize text regions from a preprocessed page image."""


class MockOCRProvider:
    """No-key provider for integration tests and wiring checks; it never invents text."""

    name = "mock"
    version = "1"

    def recognize(self, image_bytes: bytes, *, page_number: int | None) -> OCRProviderResponse:
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
        return OCRProviderResponse(
            blocks=(),
            raw_payload={
                "simulated": True,
                "message": "Mock provider performs no text recognition.",
                "image_width": width,
                "image_height": height,
                "page_number": page_number,
            },
            provider=self.name,
            provider_version=self.version,
        )


def preprocess_image(original_bytes: bytes, *, rotation: int = 0) -> tuple[bytes, ImageQualityReport]:
    """Create an in-memory OCR derivative while preserving the immutable original file."""
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("rotation must be one of 0, 90, 180, or 270.")
    try:
        with Image.open(BytesIO(original_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError("Stored page image cannot be decoded.") from exc

    if rotation:
        image = image.rotate(-rotation, expand=True)
    gray = ImageOps.grayscale(image)
    grayscale_stddev = float(Image.Stat(gray).stddev[0])
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_stddev = float(Image.Stat(edges).stddev[0])
    warnings: list[str] = []
    if min(image.size) < 900:
        warnings.append("low_resolution")
    blank = grayscale_stddev < 5.0
    blurry = edge_stddev < 8.0
    if blank:
        warnings.append("blank_or_low_contrast")
    if blurry:
        warnings.append("blur_suspected")

    # Autocontrast and a restrained contrast boost help scanned pages without
    # changing the source asset. No perspective correction is attempted here.
    prepared = ImageOps.autocontrast(gray)
    prepared = ImageEnhance.Contrast(prepared).enhance(1.15)
    output = BytesIO()
    prepared.save(output, format="PNG", optimize=True)
    return output.getvalue(), ImageQualityReport(
        width=image.width,
        height=image.height,
        grayscale_stddev=round(grayscale_stddev, 3),
        edge_stddev=round(edge_stddev, 3),
        is_blank_suspected=blank,
        is_blurry_suspected=blurry,
        warnings=tuple(warnings),
    )


def normalize_response(response: OCRProviderResponse) -> dict[str, object]:
    """Validate and serialize provider regions into the stable application schema."""
    blocks: list[dict[str, object]] = []
    for index, block in enumerate(response.blocks):
        text = block.text.strip()
        if not text:
            continue
        if block.confidence is not None and not 0.0 <= block.confidence <= 1.0:
            raise ValueError(f"OCR block {index} confidence must be between 0 and 1.")
        bbox = block.bbox
        if bbox is not None:
            if len(bbox) != 4 or any(value < 0 or value > 1 for value in bbox):
                raise ValueError(f"OCR block {index} bbox must contain four normalized values.")
            if bbox[2] < bbox[0] or bbox[3] < bbox[1]:
                raise ValueError(f"OCR block {index} bbox coordinates are inverted.")
        blocks.append(
            {
                "block_key": f"ocr-{index + 1:04d}",
                "block_type": block.block_type,
                "text": text,
                "bbox": list(bbox) if bbox is not None else None,
                "confidence": block.confidence,
                "sort_order": len(blocks),
            }
        )
    return {
        "schema_version": "1.0",
        "provider": response.provider,
        "provider_version": response.provider_version,
        "blocks": blocks,
        "block_count": len(blocks),
    }


class OCRPageNotFoundError(LookupError):
    """Raised when the requested active page does not exist."""


class OCRService:
    """Run OCR as an immutable ProcessingRun attempt for one original page."""

    def __init__(
        self,
        session: Session,
        provider: OCRProvider | None = None,
        storage: ImageStorage | None = None,
    ) -> None:
        self.session = session
        self.provider = provider or MockOCRProvider()
        self.storage = storage or ImageStorage()

    def process_page(self, chapter_id: str, page_id: str) -> ProcessingRun:
        page = self.session.scalar(
            select(ChapterPage).where(
                ChapterPage.id == page_id,
                ChapterPage.chapter_id == chapter_id,
                ChapterPage.status == "stored",
            )
        )
        if page is None:
            raise OCRPageNotFoundError("Active page not found.")

        run = ProcessingRun(
            chapter_id=chapter_id,
            page_id=page.id,
            task_type="ocr",
            provider=self.provider.name,
            provider_version=self.provider.version,
            status="queued",
            config={"preprocessing": "grayscale_autocontrast_v1", "rotation": page.rotation},
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        run.status = "running"
        run.started_at = utc_now()
        self.session.commit()
        try:
            original_path = self.storage.resolve(page.storage_path)
            if not original_path.is_file():
                raise FileNotFoundError("Original page image is missing from storage.")
            original_bytes = original_path.read_bytes()
            prepared_bytes, quality = preprocess_image(original_bytes, rotation=page.rotation)
            provider_response = self.provider.recognize(
                prepared_bytes, page_number=page.textbook_page_number
            )
            normalized = normalize_response(provider_response)
            run.raw_result = provider_response.raw_payload
            run.normalized_result = normalized
            run.quality_report = quality.to_dict()
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
