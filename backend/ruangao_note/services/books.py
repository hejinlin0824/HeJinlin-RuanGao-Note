"""Application-level operations for textbook records."""

from sqlalchemy.orm import Session

from ruangao_note.domain.models import Book
from ruangao_note.repositories.books import BookRepository


class BookService:
    """Coordinate book validation and repository operations."""

    def __init__(self, session: Session) -> None:
        self.repository = BookRepository(session)

    def create_book(
        self,
        *,
        title: str,
        edition: str | None = None,
        exam_track: str | None = None,
    ) -> Book:
        """Create a book after validating user-facing fields."""
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Book title must not be empty.")

        return self.repository.add(
            Book(title=normalized_title, edition=edition, exam_track=exam_track)
        )

    def get_book(self, book_id: str) -> Book | None:
        """Retrieve one book."""
        return self.repository.get(book_id)

    def list_books(self, *, limit: int = 100, offset: int = 0) -> list[Book]:
        """List books with bounded pagination."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if offset < 0:
            raise ValueError("offset must not be negative.")
        return self.repository.list(limit=limit, offset=offset)
