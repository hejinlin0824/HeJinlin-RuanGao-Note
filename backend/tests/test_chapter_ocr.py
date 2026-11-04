"""Tests for chapter-level PDF assembly and MinerU result handling."""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

from PIL import Image
from sqlalchemy.orm import Session

from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine
from ruangao_note.domain.models import Book, Chapter, ProcessingRun, SourceBlock
from ruangao_note.services.chapter_ocr import (
    ChapterOCRService,
    build_chapter_pdf,
)
from ruangao_note.services.image_storage import ImageStorage
from ruangao_note.services.mineru_cloud import (
    MinerUCloudParser,
    MinerUError,
    MinerUSettings,
)
from ruangao_note.services.pages import PageService, PageUpload
from ruangao_note.services.source_blocks import (
    build_source_block_payloads,
    materialize_source_blocks,
    render_anchored_markdown,
)


def image_bytes(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (1200, 1600), color).save(stream, format="PNG")
    return stream.getvalue()


def chapter_context(tmp_path):
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    book = Book(title="MinerU chapter test")
    chapter = Chapter(book=book, chapter_number=1, title="Chapter one")
    session.add(chapter)
    session.commit()
    storage = ImageStorage(tmp_path)
    uploaded = PageService(session, storage).upload(
        chapter.id,
        [
            PageUpload("page-01.png", image_bytes("white")),
            PageUpload("page-02.png", image_bytes("black")),
        ],
    )
    return engine, session, chapter, uploaded["pages"], storage


def test_chapter_pages_are_combined_into_one_ordered_pdf_without_mutating_sources(tmp_path):
    engine, session, chapter, pages, storage = chapter_context(tmp_path)
    try:
        original_bytes = [
            storage.resolve(page.storage_path).read_bytes() for page in pages
        ]
        pdf_bytes, references = build_chapter_pdf(pages, storage)

        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 1000
        assert [item.pdf_page_index for item in references] == [1, 2]
        assert [item.chapter_page_id for item in references] == [
            page.id for page in pages
        ]
        assert [item.sort_order for item in references] == [0, 1]
        assert [
            storage.resolve(page.storage_path).read_bytes() for page in pages
        ] == original_bytes
    finally:
        session.close()
        engine.dispose()


def test_chapter_ocr_creates_one_processing_run_for_all_pages(tmp_path, monkeypatch):
    engine, session, chapter, pages, storage = chapter_context(tmp_path)

    class FakeParser:
        def parse_pdf(
            self, pdf_bytes: bytes, filename: str, *, on_batch_created=None
        ) -> dict:
            assert pdf_bytes.startswith(b"%PDF")
            assert filename.endswith(".pdf")
            if on_batch_created is not None:
                on_batch_created("batch-test-001")
            return {
                "batch_id": "batch-test-001",
                "state": "done",
                "model_version": "vlm",
                "language": "ch",
                "artifacts": {
                    "markdown": {"full.md": "# Chapter\n\nRecognized text"},
                    "json": {},
                    "files": ["full.md"],
                },
            }

    monkeypatch.setattr(
        "ruangao_note.services.chapter_ocr.get_settings",
        lambda: SimpleNamespace(mineru_model_version="vlm"),
    )
    try:
        run = ChapterOCRService(
            session, storage=storage, parser=FakeParser()
        ).process_chapter(chapter.id)

        assert run.status == "succeeded"
        assert run.task_type == "chapter_ocr"
        assert run.page_id is None
        assert run.raw_result["batch_id"] == "batch-test-001"
        assert run.raw_result["page_count"] == 2
        assert run.normalized_result["page_count"] == 2
        assert run.normalized_result["artifacts"]["markdown"]["full.md"].startswith(
            "# Chapter"
        )
        assert len(
            session.query(ProcessingRun)
            .filter_by(chapter_id=chapter.id, task_type="chapter_ocr")
            .all()
        ) == 1
    finally:
        session.close()
        engine.dispose()


def test_chapter_ocr_preserves_batch_id_when_network_fails_after_submission(
    tmp_path, monkeypatch
):
    engine, session, chapter, pages, storage = chapter_context(tmp_path)

    class InterruptedParser:
        def parse_pdf(
            self, pdf_bytes: bytes, filename: str, *, on_batch_created=None
        ) -> dict:
            assert on_batch_created is not None
            on_batch_created("batch-created-before-disconnect")
            raise RuntimeError("Network error while uploading the PDF: ConnectError")

    monkeypatch.setattr(
        "ruangao_note.services.chapter_ocr.get_settings",
        lambda: SimpleNamespace(mineru_model_version="vlm"),
    )
    try:
        run = ChapterOCRService(
            session, storage=storage, parser=InterruptedParser()
        ).process_chapter(chapter.id)

        assert run.status == "failed"
        assert run.raw_result["batch_id"] == "batch-created-before-disconnect"
        assert run.raw_result["state"] == "submitted"
        assert "ConnectError" in run.error_message
    finally:
        session.close()
        engine.dispose()


def test_failed_chapter_ocr_run_resumes_existing_batch_without_resubmission(
    tmp_path, monkeypatch
):
    engine, session, chapter, pages, storage = chapter_context(tmp_path)
    batch_calls = []

    class RecoveryParser:
        def resume_batch(self, batch_id: str) -> dict:
            batch_calls.append(batch_id)
            return {
                "batch_id": batch_id,
                "state": "done",
                "model_version": "vlm",
                "language": "ch",
                "artifacts": {
                    "markdown": {"full.md": "# Recovered chapter"},
                    "json": {},
                    "files": ["full.md"],
                },
            }

        def parse_pdf(self, *args, **kwargs):
            raise AssertionError("Recovery must never resubmit the PDF.")

    monkeypatch.setattr(
        "ruangao_note.services.chapter_ocr.get_settings",
        lambda: SimpleNamespace(
            mineru_token="test-token",
            mineru_api_base_url="https://mineru.net",
            mineru_model_version="vlm",
            mineru_language="ch",
            mineru_poll_interval_seconds=0.01,
            mineru_max_wait_seconds=1,
        ),
    )
    try:
        failed = ProcessingRun(
            chapter_id=chapter.id,
            page_id=None,
            task_type="chapter_ocr",
            provider="mineru_cloud",
            provider_version="vlm",
            status="failed",
            raw_result={
                "batch_id": "existing-batch-123",
                "state": "submitted",
                "page_count": 2,
                "page_references": [{"pdf_page_index": 1, "chapter_page_id": pages[0].id}],
            },
            error_message="ZIP download disconnected",
        )
        session.add(failed)
        session.commit()
        session.refresh(failed)

        recovered = ChapterOCRService(
            session, storage=storage, parser=RecoveryParser()
        ).resume_run(chapter.id, failed.id)

        assert recovered.status == "succeeded"
        assert recovered.raw_result["batch_id"] == "existing-batch-123"
        assert recovered.raw_result["recovery"]["resubmitted"] is False
        assert recovered.normalized_result["page_count"] == 2
        assert recovered.normalized_result["artifacts"]["markdown"]["full.md"] == (
            "# Recovered chapter"
        )
        assert batch_calls == ["existing-batch-123"]
    finally:
        session.close()
        engine.dispose()




def test_mineru_content_list_maps_blocks_and_flags_cleanup_candidates_without_deleting():
    artifacts = {
        "json": {
            "content_list.json": [
                {"type": "text", "page_idx": 0, "bbox": [10, 20, 300, 45],
                 "text": "版权所有 示例教材"},
                {"type": "title", "page_idx": 0, "bbox": [10, 60, 500, 90],
                 "text": "第一章 系统架构"},
                {"type": "text", "page_idx": 0, "text": "arXiv: 2401.12345 论文水印"},
                {"type": "footnote", "page_idx": 0, "text": "[1] 这是脚注内容"},
                {"type": "table", "page_idx": 0, "table_body": "<table><tr><td>A</td></tr></table>"},
                {"type": "equation", "page_idx": 1, "text": "E = mc^2"},
                {"type": "text", "page_idx": 1, "text": "版权所有 示例教材"},
                {"type": "image", "page_idx": 1, "image_caption": ["图 1：系统结构图"]},
            ]
        }
    }
    references = [
        {"pdf_page_index": 1, "chapter_page_id": "page-a"},
        {"pdf_page_index": 2, "chapter_page_id": "page-b"},
    ]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert len(blocks) == 8
    assert blocks[0]["page_id"] == "page-a"
    assert blocks[5]["page_id"] == "page-b"
    assert blocks[4]["text"] == "<table><tr><td>A</td></tr></table>"
    assert blocks[5]["block_type"] == "equation"
    assert blocks[7]["text"] == "图 1：系统结构图"
    reasons = {
        reason
        for candidate in report["cleanup_candidates"]
        for reason in candidate["reasons"]
    }
    assert "possible_watermark_or_publication_metadata" in reasons
    assert "possible_footnote" in reasons
    assert "repeated_short_text_across_pages" in reasons
    assert all(candidate["action"] == "review_only" for candidate in report["cleanup_candidates"])


def test_source_block_materialization_is_idempotent_and_keeps_page_anchor(tmp_path):
    engine, session, chapter, pages, storage = chapter_context(tmp_path)
    try:
        run = ProcessingRun(
            chapter_id=chapter.id,
            page_id=None,
            task_type="chapter_ocr",
            provider="mineru_cloud",
            provider_version="vlm",
            status="succeeded",
            normalized_result={
                "page_references": [
                    {"pdf_page_index": 1, "chapter_page_id": pages[0].id},
                    {"pdf_page_index": 2, "chapter_page_id": pages[1].id},
                ],
                "artifacts": {
                    "json": {
                        "content_list.json": [
                            {"type": "title", "page_idx": 0, "text": "第一节"},
                            {"type": "text", "page_idx": 1, "text": "正文段落"},
                        ]
                    }
                },
            },
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        blocks, report = materialize_source_blocks(session, run)
        session.commit()
        first_ids = [block.id for block in blocks]
        again, _ = materialize_source_blocks(session, run)

        assert report["blocks_created"] == 2
        assert [block.page_id for block in blocks] == [pages[0].id, pages[1].id]
        assert [block.id for block in again] == first_ids
        assert len(session.query(SourceBlock).filter_by(processing_run_id=run.id).all()) == 2
        markdown = render_anchored_markdown(blocks)
        assert f"<!-- source:{blocks[0].block_key} -->" in markdown
        assert "## 第一节" in markdown
    finally:
        session.close()
        engine.dispose()

def test_mineru_zip_parser_reads_markdown_and_json():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("full.md", "# Test chapter")
        archive.writestr("layout.json", '{"pages": [{"page_idx": 0}]}')

    result = MinerUCloudParser._read_result_zip(stream.getvalue())

    assert result["markdown"]["full.md"] == "# Test chapter"
    assert result["json"]["layout.json"]["pages"][0]["page_idx"] == 0
    assert set(result["files"]) == {"full.md", "layout.json"}



def test_mineru_result_download_uses_direct_fresh_client_and_streams_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("full.md", "# Direct download")

    class FakeResponse:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            payload = stream.getvalue()
            yield payload[:12]
            yield payload[12:]

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            assert method == "GET"
            assert url.startswith("https://cdn.example/")
            return FakeResponse()

    parser = MinerUCloudParser(
        MinerUSettings(token="test-token"),
        client_factory=FakeClient,
        sleep=lambda _: None,
    )

    result = parser._download_result_zip(
        "https://cdn.example/signed-result.zip?signature=hidden",
        "batch-direct-test",
    )

    assert result["markdown"]["full.md"] == "# Direct download"
    assert parser.last_download_diagnostics["host"] == "cdn.example"
    assert parser.last_download_diagnostics["http_status"] == 200
    assert parser.last_download_diagnostics["attempts"] == 1
    assert parser.last_download_diagnostics["proxy"] == "disabled"




def test_mineru_result_download_uses_only_explicitly_configured_proxy():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("full.md", "# Proxied download")

    class FakeResponse:
        status_code = 200
        headers = {"content-length": str(len(stream.getvalue()))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield stream.getvalue()

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["proxy"] == "http://127.0.0.1:7890"
            assert kwargs["follow_redirects"] is True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            return FakeResponse()

    parser = MinerUCloudParser(
        MinerUSettings(
            token="test-token",
            download_proxy="http://127.0.0.1:7890",
        ),
        client_factory=FakeClient,
        sleep=lambda _: None,
    )

    result = parser._download_result_zip(
        "https://cdn.example/signed-result.zip?signature=must-not-be-logged",
        "batch-proxy-test",
    )

    assert result["markdown"]["full.md"] == "# Proxied download"
    assert parser.last_download_diagnostics["proxy"] == "explicit:http://127.0.0.1:7890"
    assert "signature" not in str(parser.last_download_diagnostics)

def test_mineru_zip_parser_rejects_path_traversal():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    try:
        MinerUCloudParser._read_result_zip(stream.getvalue())
    except MinerUError as exc:
        assert "unsafe file path" in str(exc)
    else:
        raise AssertionError("Unsafe ZIP path was accepted.")
