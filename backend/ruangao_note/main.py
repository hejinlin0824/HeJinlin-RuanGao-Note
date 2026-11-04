"""FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ruangao_note import __version__
from ruangao_note.api.ocr_routes import router as ocr_router
from ruangao_note.api.routes import router as library_router
from ruangao_note.core.config import get_settings
from ruangao_note.db.session import get_engine

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="A traceable textbook knowledge structuring and review system.",
)


app.include_router(library_router)
app.include_router(ocr_router)


@app.get("/mineru-test", include_in_schema=False)
def mineru_test_page() -> FileResponse:
    """Serve the standalone MinerU batch-upload and OCR acceptance page."""
    page = Path(__file__).resolve().parent / "static" / "mineru_test.html"
    return FileResponse(page, media_type="text/html; charset=utf-8")


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Return process liveness without depending on external services."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    """Check that the configured database can accept a simple query."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is not ready.",
        ) from exc
    return {"status": "ready"}
