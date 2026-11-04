"""Typed application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env file."""

    app_name: str = "RuanGao Note API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./data/ruangao_note.db"
    storage_dir: str = "./data/uploads"
    max_image_bytes: int = 20 * 1024 * 1024
    max_batch_upload_bytes: int = 300 * 1024 * 1024
    max_batch_upload_count: int = 30
    max_image_pixels: int = 60_000_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
