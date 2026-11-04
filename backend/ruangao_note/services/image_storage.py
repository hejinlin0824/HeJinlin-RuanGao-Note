"""Validated, atomic storage for original textbook page images."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from ruangao_note.core.config import get_settings


FORMAT_INFO = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
    "TIFF": ("image/tiff", ".tiff"),
}


class InvalidImageError(ValueError):
    """Raised when uploaded bytes are not an allowed, valid image."""


@dataclass(frozen=True)
class StoredImage:
    """Metadata for one validated image written to local storage."""

    storage_path: str
    sha256: str
    mime_type: str
    byte_size: int
    width: int
    height: int


class ImageStorage:
    """Store immutable original images below a configured storage directory."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or get_settings().storage_dir).expanduser().resolve()

    def validate(self, content: bytes) -> tuple[str, int, int, str]:
        """Validate image structure and return MIME, dimensions, and extension."""
        if not content:
            raise InvalidImageError("Uploaded image is empty.")
        settings = get_settings()
        if len(content) > settings.max_image_bytes:
            raise InvalidImageError(
                f"Image exceeds the {settings.max_image_bytes}-byte per-file limit."
            )
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = (image.format or "").upper()
                if image_format not in FORMAT_INFO:
                    raise InvalidImageError("Only JPEG, PNG, WEBP, and TIFF images are allowed.")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
                    raise InvalidImageError(
                        "Image dimensions are invalid or exceed the pixel limit."
                    )
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise InvalidImageError("Uploaded file is not a valid supported image.") from exc
        mime_type, extension = FORMAT_INFO[image_format]
        return mime_type, width, height, extension

    def save(self, content: bytes, *, book_id: str, chapter_id: str) -> StoredImage:
        """Atomically persist bytes under generated path segments, never user paths."""
        mime_type, width, height, extension = self.validate(content)
        digest = hashlib.sha256(content).hexdigest()
        relative_dir = Path("books") / book_id / chapter_id
        target_dir = (self.root / relative_dir).resolve()
        if not target_dir.is_relative_to(self.root):
            raise ValueError("Resolved storage directory escapes the configured root.")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{uuid4().hex}{extension}"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=target_dir, prefix=".upload-", suffix=".tmp", delete=False
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        return StoredImage(
            storage_path=(relative_dir / target.name).as_posix(),
            sha256=digest,
            mime_type=mime_type,
            byte_size=len(content),
            width=width,
            height=height,
        )

    def resolve(self, storage_path: str) -> Path:
        """Resolve a database relative path and reject traversal outside storage root."""
        candidate = (self.root / storage_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Stored image path escapes the configured storage root.")
        return candidate

    def remove(self, storage_path: str) -> None:
        """Remove a newly-created file during transaction rollback."""
        self.resolve(storage_path).unlink(missing_ok=True)
