"""Pydantic request schemas for TP-06 outline review."""

from pydantic import BaseModel, ConfigDict, Field


class SectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    section_number: str | None = Field(default=None, max_length=80)
    level: int | None = Field(default=None, ge=1, le=12)
    parent_id: str | None = None
    sort_order: int | None = Field(default=None, ge=0)
    actor: str = Field(default="user", max_length=120)
    reason: str | None = Field(default=None, max_length=1000)
