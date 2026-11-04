"""Database engine and session factory helpers."""

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ruangao_note.core.config import get_settings


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create an engine and enable SQLite foreign-key enforcement.

    SQLite does not create missing parent directories, so file-backed databases
    create their parent directory before the first connection.
    """
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        raw_path = database_url.removeprefix("sqlite:///")
        if raw_path and not raw_path.startswith(":memory:"):
            database_path = Path(raw_path)
            if not database_path.is_absolute():
                database_path = Path.cwd() / database_path
            database_path.parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, echo=echo, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide engine configured by application settings."""
    settings = get_settings()
    return create_database_engine(settings.database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide SQLAlchemy session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    """Yield a request-scoped session and always close it afterwards."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
