"""Application-service tests."""

import pytest

from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine
from ruangao_note.services.books import BookService
from sqlalchemy.orm import Session


def test_book_service_normalizes_title_and_persists_record() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            service = BookService(session)
            book = service.create_book(title="  软件设计师教程  ", edition="第 5 版")
            session.commit()

            assert book.id
            assert service.get_book(book.id) is book
            assert service.list_books(limit=10) == [book]
            assert book.title == "软件设计师教程"
    finally:
        engine.dispose()


def test_book_service_rejects_invalid_input() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    try:
        with Session(engine) as session:
            service = BookService(session)
            with pytest.raises(ValueError, match="title"):
                service.create_book(title="   ")
            with pytest.raises(ValueError, match="limit"):
                service.list_books(limit=0)
            with pytest.raises(ValueError, match="offset"):
                service.list_books(offset=-1)
    finally:
        engine.dispose()
