"""OCR execution and processing-run history endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.core.config import get_settings
from ruangao_note.db.session import get_db
from ruangao_note.domain.models import ProcessingRun, SourceBlock
from ruangao_note.services.chapter_ocr import (
    ChapterOCRNotFoundError,
    ChapterOCRResumeConflictError,
    ChapterOCRService,
)
from ruangao_note.services.ocr import OCRPageNotFoundError, OCRService
from ruangao_note.services.source_blocks import (
    materialize_source_blocks,
    render_anchored_markdown,
)

router = APIRouter(prefix="/api", tags=["ocr"])


def _run_payload(run: ProcessingRun) -> dict[str, object]:
    return {
        "id": run.id,
        "chapter_id": run.chapter_id,
        "page_id": run.page_id,
        "task_type": run.task_type,
        "provider": run.provider,
        "provider_version": run.provider_version,
        "status": run.status,
        "config": run.config,
        "raw_result": run.raw_result,
        "normalized_result": run.normalized_result,
        "quality_report": run.quality_report,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
    }




def _source_block_payload(block: SourceBlock) -> dict[str, object]:
    return {
        "id": block.id,
        "chapter_id": block.chapter_id,
        "page_id": block.page_id,
        "processing_run_id": block.processing_run_id,
        "block_key": block.block_key,
        "block_type": block.block_type,
        "text": block.text,
        "bbox": block.bbox,
        "confidence": block.confidence,
        "content_hash": block.content_hash,
        "version": block.version,
        "sort_order": block.sort_order,
        "is_active": block.is_active,
        "image_url": f"/api/chapters/{block.chapter_id}/pages/{block.page_id}/image",
    }


@router.post("/chapters/{chapter_id}/ocr-runs/{run_id}/source-blocks")
def create_chapter_source_blocks(
    chapter_id: str, run_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    """Materialize page-linked SourceBlocks from a successful MinerU layout result."""
    run = session.scalar(
        select(ProcessingRun).where(
            ProcessingRun.id == run_id,
            ProcessingRun.chapter_id == chapter_id,
            ProcessingRun.task_type == "chapter_ocr",
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="OCR run not found in this chapter.")
    if run.status != "succeeded":
        raise HTTPException(status_code=409, detail="SourceBlocks require a successful OCR run.")
    blocks, report = materialize_source_blocks(session, run)
    quality = dict(run.quality_report or {})
    quality["source_blocks"] = report
    run.quality_report = quality
    if blocks:
        normalized = dict(run.normalized_result or {})
        normalized["source_block_count"] = len(blocks)
        normalized["anchored_markdown"] = render_anchored_markdown(blocks, report)
        run.normalized_result = normalized
    session.commit()
    return {
        "run_id": run.id,
        "count": len(blocks),
        "report": report,
        "items": [_source_block_payload(block) for block in blocks],
        "anchored_markdown": (run.normalized_result or {}).get("anchored_markdown", ""),
    }


@router.get("/chapters/{chapter_id}/ocr-runs/{run_id}/source-blocks")
def list_chapter_source_blocks(
    chapter_id: str, run_id: str, session: Session = Depends(get_db)
) -> list[dict[str, object]]:
    """List source blocks for one OCR processing version."""
    run_exists = session.scalar(
        select(ProcessingRun.id).where(
            ProcessingRun.id == run_id,
            ProcessingRun.chapter_id == chapter_id,
            ProcessingRun.task_type == "chapter_ocr",
        )
    )
    if run_exists is None:
        raise HTTPException(status_code=404, detail="OCR run not found in this chapter.")
    blocks = session.scalars(
        select(SourceBlock)
        .where(SourceBlock.processing_run_id == run_id)
        .order_by(SourceBlock.sort_order, SourceBlock.id)
    ).all()
    return [_source_block_payload(block) for block in blocks]


@router.post("/chapters/{chapter_id}/ocr")
def run_chapter_ocr(
    chapter_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    """Parse all active pages in one chapter-level MinerU batch task."""
    settings = get_settings()
    if not settings.mineru_token.strip():
        raise HTTPException(
            status_code=503,
            detail="MinerU token is not configured. Set MINERU_TOKEN in the local .env file.",
        )
    try:
        run = ChapterOCRService(session).process_chapter(chapter_id)
    except ChapterOCRNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run_payload(run)


@router.post("/chapters/{chapter_id}/ocr-runs/{run_id}/resume")
def resume_chapter_ocr(
    chapter_id: str, run_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    """Retry retrieval for a saved MinerU batch without re-uploading the source PDF."""
    settings = get_settings()
    if not settings.mineru_token.strip():
        raise HTTPException(
            status_code=503,
            detail="MinerU token is not configured. Set MINERU_TOKEN in the local .env file.",
        )
    try:
        run = ChapterOCRService(session).resume_run(chapter_id, run_id)
    except ChapterOCRNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChapterOCRResumeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_payload(run)


@router.get("/chapters/{chapter_id}/ocr-runs")
def list_chapter_ocr_runs(
    chapter_id: str, session: Session = Depends(get_db)
) -> list[dict[str, object]]:
    """Return newest-first chapter-level OCR attempts."""
    runs = session.scalars(
        select(ProcessingRun)
        .where(
            ProcessingRun.chapter_id == chapter_id,
            ProcessingRun.task_type == "chapter_ocr",
        )
        .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
    ).all()
    return [_run_payload(run) for run in runs]


@router.post("/chapters/{chapter_id}/pages/{page_id}/ocr")
def run_page_ocr(
    chapter_id: str, page_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    """Create a new mock OCR attempt for a single page."""
    try:
        run = OCRService(session).process_page(chapter_id, page_id)
    except OCRPageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run_payload(run)


@router.get("/chapters/{chapter_id}/pages/{page_id}/ocr-runs")
def list_page_ocr_runs(
    chapter_id: str, page_id: str, session: Session = Depends(get_db)
) -> list[dict[str, object]]:
    """Return newest-first OCR attempts for an active or archived page."""
    runs = session.scalars(
        select(ProcessingRun)
        .where(
            ProcessingRun.chapter_id == chapter_id,
            ProcessingRun.page_id == page_id,
            ProcessingRun.task_type == "ocr",
        )
        .order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
    ).all()
    return [_run_payload(run) for run in runs]
