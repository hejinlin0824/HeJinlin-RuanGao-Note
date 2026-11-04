"""OCR execution and processing-run history endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.db.session import get_db
from ruangao_note.domain.models import ProcessingRun
from ruangao_note.services.ocr import OCRPageNotFoundError, OCRService

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


@router.post("/chapters/{chapter_id}/pages/{page_id}/ocr")
def run_page_ocr(
    chapter_id: str, page_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    """Create a new OCR attempt. Calling again is an explicit retry/new version."""
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
