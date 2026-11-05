"""HTTP routes for TP-06 table-of-contents extraction and correction."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ruangao_note.api.toc_schemas import SectionUpdate
from ruangao_note.db.session import get_db
from ruangao_note.domain.models import Section
from ruangao_note.services.toc import (
    TOCNotFoundError,
    TOCService,
    TOCValidationError,
)

router = APIRouter(prefix="/api", tags=["outline"])


def _payload(section: Section) -> dict[str, object]:
    block = section.source_block
    return {
        "id": section.id,
        "chapter_id": section.chapter_id,
        "parent_id": section.parent_id,
        "title": section.title,
        "section_number": section.section_number,
        "level": section.level,
        "sort_order": section.sort_order,
        "source_block_id": section.source_block_id,
        "source_text": block.text if block else None,
        "page_id": block.page_id if block else None,
        "bbox": block.bbox if block else None,
        "image_url": (
            f"/api/chapters/{section.chapter_id}/pages/{block.page_id}/image"
            if block
            else None
        ),
    }


@router.get("/chapters/{chapter_id}/sections")
def list_chapter_sections(
    chapter_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    try:
        return TOCService(session).list_sections(chapter_id)
    except TOCNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/chapters/{chapter_id}/sections/generate")
def generate_chapter_sections(
    chapter_id: str, session: Session = Depends(get_db)
) -> dict[str, object]:
    try:
        service = TOCService(session)
        report = service.generate(chapter_id)
        session.commit()
        result = service.list_sections(chapter_id)
        return {"report": report, **result}
    except TOCNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/chapters/{chapter_id}/sections/{section_id}")
def update_chapter_section(
    chapter_id: str,
    section_id: str,
    payload: SectionUpdate,
    session: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        changes = {
            key: getattr(payload, key)
            for key in {"title", "section_number", "level", "parent_id", "sort_order"}
            if key in payload.model_fields_set
        }
        section = TOCService(session).update_section(
            chapter_id,
            section_id,
            changes,
            actor=payload.actor,
            reason=payload.reason,
        )
        session.commit()
        session.refresh(section)
        return _payload(section)
    except TOCNotFoundError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TOCValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
