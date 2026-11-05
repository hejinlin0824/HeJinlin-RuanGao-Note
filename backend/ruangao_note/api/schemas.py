"""Request and response schemas for textbook library and page APIs."""

from pydantic import BaseModel, ConfigDict, Field


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    edition: str | None = Field(default=None, max_length=120)
    exam_track: str | None = Field(default=None, max_length=160)


class BookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    edition: str | None
    exam_track: str | None


class ChapterCreate(BaseModel):
    chapter_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=300)
    sort_order: int | None = Field(default=None, ge=0)


class ChapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    book_id: str
    chapter_number: int
    title: str
    sort_order: int


class PageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chapter_id: str
    sort_order: int
    textbook_page_number: int | None
    original_filename: str
    sha256: str
    mime_type: str
    byte_size: int
    width: int | None
    height: int | None
    rotation: int
    status: str
    replaces_page_id: str | None


class PageUploadResult(BaseModel):
    pages: list[PageRead]
    duplicates: list[dict[str, str]]


class PageReorder(BaseModel):
    page_ids: list[str] = Field(min_length=1)


class PageNumberUpdate(BaseModel):
    textbook_page_number: int | None = Field(default=None, ge=1)



class PageRotationUpdate(BaseModel):
    rotation: int = Field(ge=0, le=270)
