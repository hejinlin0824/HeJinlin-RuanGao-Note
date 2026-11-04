"""Integration tests for original page image storage and lifecycle."""

from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine
from ruangao_note.domain.models import Book, Chapter, ChapterPage
from ruangao_note.services.image_storage import ImageStorage, InvalidImageError
from ruangao_note.services.pages import PageService, PageUpload


def png_bytes(color: str = "white") -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), color=color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def page_context(tmp_path):
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    book = Book(title="测试教材")
    chapter = Chapter(book=book, chapter_number=1, title="第一章")
    session.add(chapter)
    session.commit()
    yield session, chapter, ImageStorage(tmp_path)
    session.close()
    engine.dispose()


def test_batch_upload_persists_order_hash_and_image_dimensions(page_context):
    session, chapter, storage = page_context
    result = PageService(session, storage).upload(
        chapter.id,
        [
            PageUpload("one.png", png_bytes(), 1),
            PageUpload("two.png", png_bytes("black"), 2),
        ],
    )
    pages = result["pages"]
    assert [page.sort_order for page in pages] == [0, 1]
    assert [page.textbook_page_number for page in pages] == [1, 2]
    assert pages[0].width == 32
    assert pages[0].height == 24
    assert len(pages[0].sha256) == 64
    assert storage.resolve(pages[0].storage_path).is_file()


def test_duplicate_hash_is_reported_and_not_inserted(page_context):
    session, chapter, storage = page_context
    service = PageService(session, storage)
    result = service.upload(
        chapter.id, [PageUpload("one.png", png_bytes()), PageUpload("copy.png", png_bytes())]
    )
    assert len(result["pages"]) == 1
    assert result["duplicates"][0]["filename"] == "copy.png"
    assert len(service.list_pages(chapter.id)) == 1


def test_invalid_image_is_rejected(page_context):
    session, chapter, storage = page_context
    with pytest.raises(InvalidImageError):
        PageService(session, storage).upload(
            chapter.id, [PageUpload("fake.png", b"not an image")]
        )


def test_reorder_requires_exact_active_page_permutation(page_context):
    session, chapter, storage = page_context
    service = PageService(session, storage)
    pages = service.upload(
        chapter.id, [PageUpload("a.png", png_bytes()), PageUpload("b.png", png_bytes("black"))]
    )["pages"]
    reordered = service.reorder(chapter.id, [pages[1].id, pages[0].id])
    assert [page.id for page in reordered] == [pages[1].id, pages[0].id]
    with pytest.raises(ValueError, match="every active page"):
        service.reorder(chapter.id, [pages[0].id])


def test_replace_keeps_previous_original_and_creates_new_page_row(page_context):
    session, chapter, storage = page_context
    service = PageService(session, storage)
    old = service.upload(chapter.id, [PageUpload("old.png", png_bytes())])["pages"][0]
    old_path = storage.resolve(old.storage_path)
    original_order = old.sort_order
    replacement = service.replace(
        chapter.id, old.id, PageUpload("new.png", png_bytes("black"))
    )
    assert old.status == "archived"
    assert old_path.is_file()
    assert replacement.replaces_page_id == old.id
    assert replacement.sort_order == original_order


def test_storage_rejects_path_traversal(page_context):
    _, _, storage = page_context
    with pytest.raises(ValueError, match="escapes"):
        storage.resolve("../outside.png")


def test_failed_batch_removes_files_created_earlier_in_the_batch(page_context):
    _, chapter, storage = page_context
    service = PageService(_, storage)
    with pytest.raises(InvalidImageError):
        service.upload(
            chapter.id,
            [PageUpload("valid.png", png_bytes()), PageUpload("invalid.png", b"broken")],
        )
    assert list(storage.root.rglob("*.png")) == []


def test_archive_retains_file_and_compacts_active_order(page_context):
    session, chapter, storage = page_context
    service = PageService(session, storage)
    pages = service.upload(
        chapter.id,
        [PageUpload("a.png", png_bytes()), PageUpload("b.png", png_bytes("black"))],
    )["pages"]
    removed_path = storage.resolve(pages[0].storage_path)
    service.archive(chapter.id, pages[0].id)
    assert removed_path.is_file()
    active = service.list_pages(chapter.id)
    assert len(active) == 1
    assert active[0].sort_order == 0
    archived = session.scalar(select(ChapterPage).where(ChapterPage.id == pages[0].id))
    assert archived is not None and archived.status == "archived"
