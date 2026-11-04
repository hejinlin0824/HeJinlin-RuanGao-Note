"""HTTP routes for textbook library and page asset management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ruangao_note.api.schemas import (
    BookCreate,
    BookRead,
    ChapterCreate,
    ChapterRead,
    PageNumberUpdate,
    PageRead,
    PageReorder,
    PageRotationUpdate,
    PageUploadResult,
)
from ruangao_note.core.config import get_settings
from ruangao_note.db.session import get_db
from ruangao_note.domain.models import Book, Chapter, ChapterPage
from ruangao_note.services.image_storage import ImageStorage, InvalidImageError
from ruangao_note.services.pages import (
    DuplicatePageError,
    PageNotFoundError,
    PageService,
    PageUpload,
)

router = APIRouter(prefix="/api", tags=["library"])


@router.post("/books", response_model=BookRead, status_code=status.HTTP_201_CREATED)
def create_book(payload: BookCreate, session: Session = Depends(get_db)) -> Book:
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Book title must not be empty.")
    book = Book(title=title, edition=payload.edition, exam_track=payload.exam_track)
    session.add(book)
    session.commit()
    session.refresh(book)
    return book


@router.get("/books", response_model=list[BookRead])
def list_books(
    limit: int = 100, offset: int = 0, session: Session = Depends(get_db)
) -> list[Book]:
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(status_code=422, detail="Invalid pagination values.")
    return list(
        session.scalars(
            select(Book).order_by(Book.created_at.desc()).limit(limit).offset(offset)
        ).all()
    )


@router.get("/books/{book_id}/chapters", response_model=list[ChapterRead])
def list_chapters(book_id: str, session: Session = Depends(get_db)) -> list[Chapter]:
    if session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    return list(
        session.scalars(
            select(Chapter)
            .where(Chapter.book_id == book_id)
            .order_by(Chapter.sort_order, Chapter.chapter_number)
        ).all()
    )


@router.post(
    "/books/{book_id}/chapters",
    response_model=ChapterRead,
    status_code=status.HTTP_201_CREATED,
)
def create_chapter(
    book_id: str, payload: ChapterCreate, session: Session = Depends(get_db)
) -> Chapter:
    if session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Chapter title must not be empty.")
    if session.scalar(
        select(Chapter.id).where(
            Chapter.book_id == book_id, Chapter.chapter_number == payload.chapter_number
        )
    ):
        raise HTTPException(status_code=409, detail="Chapter number already exists in this book.")
    next_order = session.scalar(
        select(func.max(Chapter.sort_order)).where(Chapter.book_id == book_id)
    )
    order = payload.sort_order if payload.sort_order is not None else (
        next_order if next_order is not None else -1
    ) + 1
    if session.scalar(
        select(Chapter.id).where(Chapter.book_id == book_id, Chapter.sort_order == order)
    ):
        raise HTTPException(status_code=409, detail="Chapter sort order already exists.")
    chapter = Chapter(
        book_id=book_id,
        chapter_number=payload.chapter_number,
        title=title,
        sort_order=order,
    )
    session.add(chapter)
    session.commit()
    session.refresh(chapter)
    return chapter


@router.get("/chapters/{chapter_id}/pages", response_model=list[PageRead])
def list_pages(chapter_id: str, session: Session = Depends(get_db)) -> list[ChapterPage]:
    try:
        return PageService(session).list_pages(chapter_id)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/chapters/{chapter_id}/pages",
    response_model=PageUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_pages(
    chapter_id: str,
    files: list[UploadFile] = File(...),
    textbook_page_numbers: list[int] | None = Form(default=None),
    session: Session = Depends(get_db),
) -> dict[str, object]:
    settings = get_settings()
    if not 1 <= len(files) <= settings.max_batch_upload_count:
        raise HTTPException(
            status_code=422,
            detail=f"Upload between 1 and {settings.max_batch_upload_count} images per batch.",
        )
    if textbook_page_numbers is not None and len(textbook_page_numbers) != len(files):
        raise HTTPException(status_code=422, detail="Page-number count must match file count.")
    uploads: list[PageUpload] = []
    total_size = 0
    for index, file in enumerate(files):
        content = await file.read(settings.max_image_bytes + 1)
        total_size += len(content)
        if total_size > settings.max_batch_upload_bytes:
            raise HTTPException(status_code=413, detail="Upload batch exceeds the total size limit.")
        uploads.append(
            PageUpload(
                filename=file.filename or f"page-{index + 1}",
                content=content,
                textbook_page_number=(
                    textbook_page_numbers[index] if textbook_page_numbers is not None else None
                ),
            )
        )
    try:
        return PageService(session).upload(chapter_id, uploads)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidImageError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/chapters/{chapter_id}/pages/order", response_model=list[PageRead])
def reorder_pages(
    chapter_id: str, payload: PageReorder, session: Session = Depends(get_db)
) -> list[ChapterPage]:
    try:
        return PageService(session).reorder(chapter_id, payload.page_ids)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/chapters/{chapter_id}/pages/{page_id}/number", response_model=PageRead
)
def update_page_number(
    chapter_id: str,
    page_id: str,
    payload: PageNumberUpdate,
    session: Session = Depends(get_db),
) -> ChapterPage:
    try:
        return PageService(session).update_page_number(
            chapter_id, page_id, payload.textbook_page_number
        )
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/chapters/{chapter_id}/pages/{page_id}/replace",
    response_model=PageRead,
)
async def replace_page(
    chapter_id: str,
    page_id: str,
    file: UploadFile = File(...),
    textbook_page_number: int | None = Form(default=None, ge=1),
    session: Session = Depends(get_db),
) -> ChapterPage:
    settings = get_settings()
    content = await file.read(settings.max_image_bytes + 1)
    try:
        return PageService(session).replace(
            chapter_id,
            page_id,
            PageUpload(filename=file.filename or "replacement", content=content,
                       textbook_page_number=textbook_page_number),
        )
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidImageError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except DuplicatePageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/chapters/{chapter_id}/pages/{page_id}/rotation",
    response_model=PageRead,
)
def update_page_rotation(
    chapter_id: str,
    page_id: str,
    payload: PageRotationUpdate,
    session: Session = Depends(get_db),
) -> ChapterPage:
    try:
        return PageService(session).update_rotation(chapter_id, page_id, payload.rotation)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/chapters/{chapter_id}/pages/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_page(chapter_id: str, page_id: str, session: Session = Depends(get_db)) -> None:
    try:
        PageService(session).archive(chapter_id, page_id)
    except PageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/chapters/{chapter_id}/pages/{page_id}/image")
def preview_page(chapter_id: str, page_id: str, session: Session = Depends(get_db)) -> FileResponse:
    page = session.scalar(
        select(ChapterPage).where(
            ChapterPage.id == page_id,
            ChapterPage.chapter_id == chapter_id,
        )
    )
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    try:
        path = ImageStorage().resolve(page.storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid stored image path.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file is missing.")
    return FileResponse(path, media_type=page.mime_type, filename=page.original_filename)
