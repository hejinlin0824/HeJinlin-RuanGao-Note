"""Tests for provider-neutral OCR processing and image quality diagnostics."""

from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine
from ruangao_note.domain.models import Book, Chapter, ProcessingRun
from ruangao_note.services.image_storage import ImageStorage
from ruangao_note.services.ocr import (
    OCRBlock,
    OCRProviderResponse,
    OCRService,
    normalize_response,
    preprocess_image,
)
from ruangao_note.services.pages import PageService, PageUpload


def png_bytes(color: str = "white", size: tuple[int, int] = (1400, 1800)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def ocr_context(tmp_path):
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    book = Book(title="OCR 测试教材")
    chapter = Chapter(book=book, chapter_number=1, title="OCR 测试章节")
    session.add(chapter)
    session.commit()
    storage = ImageStorage(tmp_path)
    page = PageService(session, storage).upload(
        chapter.id, [PageUpload("page.png", png_bytes())]
    )["pages"][0]
    yield session, chapter, page, storage
    session.close()
    engine.dispose()


class TextProvider:
    name = "test-provider"
    version = "2026.1"

    def recognize(self, image_bytes: bytes, *, page_number: int | None) -> OCRProviderResponse:
        return OCRProviderResponse(
            blocks=(
                OCRBlock(
                    text="  软件工程是系统化的软件开发活动。 ",
                    block_type="paragraph",
                    bbox=(0.1, 0.2, 0.9, 0.4),
                    confidence=0.98,
                ),
                OCRBlock(text=""),
            ),
            raw_payload={"request_id": "test-123", "provider_page": page_number},
            provider=self.name,
            provider_version=self.version,
        )


class FailingProvider:
    name = "failing-provider"
    version = "test"

    def recognize(self, image_bytes: bytes, *, page_number: int | None) -> OCRProviderResponse:
        raise TimeoutError("provider timed out")


def test_preprocessing_returns_derivative_and_quality_report_without_mutating_source():
    original = png_bytes()
    prepared, report = preprocess_image(original, rotation=90)
    assert prepared.startswith(b"\x89PNG")
    assert (report.width, report.height) == (1800, 1400)
    assert report.grayscale_stddev == 0
    assert report.is_blank_suspected is True
    assert "blank_or_low_contrast" in report.warnings
    assert original == png_bytes()


def test_normalize_response_validates_and_keeps_bbox_and_confidence():
    normalized = normalize_response(
        OCRProviderResponse(
            blocks=(OCRBlock(" text ", bbox=(0.1, 0.2, 0.8, 0.9), confidence=0.9),),
            raw_payload={},
            provider="example",
            provider_version="1",
        )
    )
    assert normalized["schema_version"] == "1.0"
    assert normalized["block_count"] == 1
    assert normalized["blocks"][0]["text"] == "text"
    assert normalized["blocks"][0]["bbox"] == [0.1, 0.2, 0.8, 0.9]


@pytest.mark.parametrize(
    "block",
    [
        OCRBlock("bad confidence", confidence=1.1),
        OCRBlock("bad bbox", bbox=(0.1, 0.2, 1.2, 0.9)),
        OCRBlock("inverted bbox", bbox=(0.8, 0.2, 0.1, 0.9)),
    ],
)
def test_normalize_response_rejects_invalid_provider_geometry_or_confidence(block):
    with pytest.raises(ValueError):
        normalize_response(
            OCRProviderResponse((block,), {}, "example", "1")
        )


def test_ocr_service_persists_raw_normalized_and_quality_results(ocr_context):
    session, chapter, page, storage = ocr_context
    original_path = storage.resolve(page.storage_path)
    original_bytes = original_path.read_bytes()

    run = OCRService(session, provider=TextProvider(), storage=storage).process_page(
        chapter.id, page.id
    )

    assert run.status == "succeeded"
    assert run.provider == "test-provider"
    assert run.raw_result == {"request_id": "test-123", "provider_page": None}
    assert run.normalized_result["block_count"] == 1
    assert run.normalized_result["blocks"][0]["confidence"] == 0.98
    assert run.quality_report["width"] == 1400
    assert run.started_at is not None and run.completed_at is not None
    assert original_path.read_bytes() == original_bytes
    assert session.scalar(select(ProcessingRun).where(ProcessingRun.id == run.id)) is not None


def test_mock_provider_is_explicitly_simulated_and_does_not_invent_text(ocr_context):
    session, chapter, page, storage = ocr_context
    run = OCRService(session, storage=storage).process_page(chapter.id, page.id)
    assert run.status == "succeeded"
    assert run.provider == "mock"
    assert run.raw_result["simulated"] is True
    assert run.normalized_result["blocks"] == []


def test_provider_failure_is_recorded_and_retry_creates_a_new_attempt(ocr_context):
    session, chapter, page, storage = ocr_context
    failed = OCRService(session, provider=FailingProvider(), storage=storage).process_page(
        chapter.id, page.id
    )
    assert failed.status == "failed"
    assert "TimeoutError" in failed.error_message
    assert failed.completed_at is not None

    retried = OCRService(session, provider=TextProvider(), storage=storage).process_page(
        chapter.id, page.id
    )
    assert retried.status == "succeeded"
    assert retried.id != failed.id
    attempts = session.scalars(
        select(ProcessingRun).where(
            ProcessingRun.page_id == page.id, ProcessingRun.task_type == "ocr"
        )
    ).all()
    assert len(attempts) == 2


def test_ocr_rejects_archived_page(ocr_context):
    session, chapter, page, storage = ocr_context
    PageService(session, storage).archive(chapter.id, page.id)
    from ruangao_note.services.ocr import OCRPageNotFoundError

    with pytest.raises(OCRPageNotFoundError):
        OCRService(session, storage=storage).process_page(chapter.id, page.id)
