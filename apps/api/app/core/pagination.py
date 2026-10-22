from __future__ import annotations

from pydantic import BaseModel, Field


class CursorParams(BaseModel):
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None