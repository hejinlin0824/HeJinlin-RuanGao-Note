"""Page import, ordering, replacement, and archival operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ruangao_note.domain.models import Chapter, ChapterPage
from ruangao_note.services.image_storage import ImageStorage


@dataclass(frozen=True)
class PageUpload:
    """One uploaded file and optional textbook page number."""

    filename: str
    content: bytes
    textbook_page_number: int | None = None


class PageNotFoundError(LookupError):
    """Raised when a page or chapter does not exist."""


class DuplicatePageError(ValueError):
    """Raised when a replacement duplicates another active page."""


class PageService:
    """Coordinate database page metadata with immutable image files."""

    def __init__(self, session: Session, storage: ImageStorage | None = None) -> None:
        self.session = session
        self.storage = storage or ImageStorage()

    def upload(self, chapter_id: str, uploads: list[PageUpload]) -> dict[str, object]:
        """Save a batch; duplicate hashes are reported and skipped, not silently discarded."""
        chapter = self.session.get(Chapter, chapter_id)
        if chapter is None:
            raise PageNotFoundError("Chapter not found.")
        if not uploads:
            raise ValueError("At least one image is required.")
        existing_hashes = set(
            self.session.scalars(
                select(ChapterPage.sha256).where(
                    ChapterPage.chapter_id == chapter_id, ChapterPage.status == "stored"
                )
            ).all()
        )
        created_paths: list[str] = []
        pages: list[ChapterPage] = []
        duplicates: list[dict[str, str]] = []
        next_order = self._next_order(chapter_id)
        try:
            for upload in uploads:
                stored = self.storage.save(
                    upload.content, book_id=chapter.book_id, chapter_id=chapter_id
                )
                if stored.sha256 in existing_hashes:
                    self.storage.remove(stored.storage_path)
                    duplicates.append({"filename": upload.filename, "sha256": stored.sha256})
                    continue
                existing_hashes.add(stored.sha256)
                created_paths.append(stored.storage_path)
                safe_name = PurePath(upload.filename.replace("\\", "/")).name[:500] or "page"
                page = ChapterPage(
                    chapter_id=chapter_id,
                    sort_order=next_order,
                    textbook_page_number=upload.textbook_page_number,
                    original_filename=safe_name,
                    storage_path=stored.storage_path,
                    sha256=stored.sha256,
                    mime_type=stored.mime_type,
                    byte_size=stored.byte_size,
                    width=stored.width,
                    height=stored.height,
                    status="stored",
                )
                pages.append(page)
                next_order += 1
            self.session.add_all(pages)
            self.session.commit()
            return {"pages": pages, "duplicates": duplicates}
        except Exception:
            self.session.rollback()
            for path in created_paths:
                self.storage.remove(path)
            raise

    def list_pages(self, chapter_id: str) -> list[ChapterPage]:
        """List current, non-archived pages in stable page order."""
        if self.session.get(Chapter, chapter_id) is None:
            raise PageNotFoundError("Chapter not found.")
        return list(
            self.session.scalars(
                select(ChapterPage)
                .where(ChapterPage.chapter_id == chapter_id, ChapterPage.status == "stored")
                .order_by(ChapterPage.sort_order, ChapterPage.id)
            ).all()
        )

    def reorder(self, chapter_id: str, page_ids: list[str]) -> list[ChapterPage]:
        """Persist a complete permutation without violating the unique order constraint."""
        pages = self.list_pages(chapter_id)
        current_ids = {page.id for page in pages}
        if len(page_ids) != len(set(page_ids)) or set(page_ids) != current_ids:
            raise ValueError("page_ids must contain every active page exactly once.")
        offset = self._max_order(chapter_id) + len(pages) + 100
        try:
            for index, page in enumerate(pages):
                page.sort_order = offset + index
            self.session.flush()
            by_id = {page.id: page for page in pages}
            for index, page_id in enumerate(page_ids):
                by_id[page_id].sort_order = index
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self.list_pages(chapter_id)

    def update_page_number(
        self, chapter_id: str, page_id: str, textbook_page_number: int | None
    ) -> ChapterPage:
        """Update the printed page number without changing image bytes."""
        page = self._get_active_page(chapter_id, page_id)
        if textbook_page_number is not None and textbook_page_number < 1:
            raise ValueError("textbook_page_number must be positive.")
        page.textbook_page_number = textbook_page_number
        self.session.commit()
        return page

    def archive(self, chapter_id: str, page_id: str) -> None:
        """Soft-delete a page and retain its original image and database record."""
        page = self._get_active_page(chapter_id, page_id)
        pages = self.list_pages(chapter_id)
        offset = self._max_order(chapter_id) + len(pages) + 100
        page.status = "archived"
        page.sort_order = offset
        self.session.flush()
        remaining = [item for item in pages if item.id != page_id]
        for index, item in enumerate(remaining):
            item.sort_order = offset + len(pages) + index
        self.session.flush()
        for index, item in enumerate(remaining):
            item.sort_order = index
        self.session.commit()

    def replace(
        self, chapter_id: str, page_id: str, upload: PageUpload
    ) -> ChapterPage:
        """Archive the prior row and create a new immutable page row at its position."""
        old_page = self._get_active_page(chapter_id, page_id)
        chapter = self.session.get(Chapter, chapter_id)
        assert chapter is not None
        stored = self.storage.save(upload.content, book_id=chapter.book_id, chapter_id=chapter_id)
        duplicate = self.session.scalar(
            select(ChapterPage.id).where(
                ChapterPage.chapter_id == chapter_id,
                ChapterPage.sha256 == stored.sha256,
                ChapterPage.status == "stored",
                ChapterPage.id != page_id,
            )
        )
        if duplicate is not None:
            self.storage.remove(stored.storage_path)
            raise DuplicatePageError("Replacement image duplicates another active page.")
        original_order = old_page.sort_order
        offset = self._max_order(chapter_id) + 100
        try:
            old_page.sort_order = offset
            old_page.status = "archived"
            self.session.flush()
            safe_name = PurePath(upload.filename.replace("\\", "/")).name[:500] or "page"
            new_page = ChapterPage(
                chapter_id=chapter_id,
                sort_order=original_order,
                textbook_page_number=(
                    upload.textbook_page_number
                    if upload.textbook_page_number is not None
                    else old_page.textbook_page_number
                ),
                original_filename=safe_name,
                storage_path=stored.storage_path,
                sha256=stored.sha256,
                mime_type=stored.mime_type,
                byte_size=stored.byte_size,
                width=stored.width,
                height=stored.height,
                rotation=0,
                status="stored",
                replaces_page_id=old_page.id,
            )
            self.session.add(new_page)
            self.session.commit()
            return new_page
        except Exception:
            self.session.rollback()
            self.storage.remove(stored.storage_path)
            raise

    def _get_active_page(self, chapter_id: str, page_id: str) -> ChapterPage:
        page = self.session.scalar(
            select(ChapterPage).where(
                ChapterPage.id == page_id,
                ChapterPage.chapter_id == chapter_id,
                ChapterPage.status == "stored",
            )
        )
        if page is None:
            raise PageNotFoundError("Page not found.")
        return page

    def _max_order(self, chapter_id: str) -> int:
        value = self.session.scalar(
            select(func.max(ChapterPage.sort_order)).where(
                ChapterPage.chapter_id == chapter_id
            )
        )
        return value if value is not None else -1

    def _next_order(self, chapter_id: str) -> int:
        return self._max_order(chapter_id) + 1
