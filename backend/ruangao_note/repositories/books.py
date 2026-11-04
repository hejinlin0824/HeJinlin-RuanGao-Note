"""Persistence operations for textbook records."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.domain.models import Book


class BookRepository:
    """Encapsulate database queries for books."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, book: Book) -> Book:
        """Stage a new book and flush it to obtain generated values."""
        self.session.add(book)
        self.session.flush()
        return book

    def get(self, book_id: str) -> Book | None:
        """Return a book by its primary key."""
        return self.session.get(Book, book_id)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[Book]:
        """Return books ordered by creation time, newest first."""
        statement = select(Book).order_by(Book.created_at.desc()).limit(limit).offset(offset)
        return list(self.session.scalars(statement).all())
