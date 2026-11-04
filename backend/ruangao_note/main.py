"""FastAPI application entry point."""

from fastapi import FastAPI

from ruangao_note import __version__

app = FastAPI(
    title="RuanGao Note API",
    version=__version__,
    description="A traceable textbook knowledge structuring and review system.",
)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Return process liveness."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    """Return readiness; dependency checks will be added with TP-02."""
    return {"status": "ready"}
