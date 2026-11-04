"""Typed application settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env file."""

    app_name: str = "RuanGao Note API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/ruangao_note.db"
    storage_dir: str = "./data/uploads"
    max_image_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_batch_upload_bytes: int = Field(default=300 * 1024 * 1024, gt=0)
    max_batch_upload_count: int = Field(default=30, ge=1, le=30)
    max_image_pixels: int = Field(default=60_000_000, gt=0)

    # MinerU v4 cloud batch API. Keep the token in the ignored local .env file.
    mineru_token: str = ""
    mineru_api_base_url: str = "https://mineru.net"
    mineru_model_version: str = "vlm"
    mineru_language: str = "ch"
    mineru_poll_interval_seconds: float = Field(default=5.0, gt=0, le=60)
    mineru_max_wait_seconds: int = Field(default=1500, gt=0, le=7200)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
