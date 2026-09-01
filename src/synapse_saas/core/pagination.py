"""Pagination primitives shared by list endpoints."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = 50


class PageParams(BaseModel):
    limit: int = Field(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
    offset: int = Field(0, ge=0)


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class Page(BaseModel, Generic[T]):
    """Consistent list envelope: data + pagination metadata."""

    data: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, items: list[T], *, total: int, limit: int, offset: int) -> Page[T]:
        return cls(data=items, meta=PageMeta(total=total, limit=limit, offset=offset))


class CursorPage(BaseModel, Generic[T]):
    """Cursor-paginated envelope for append-only streams (audit logs, deliveries).

    Cursor semantics are opaque to clients; producers encode the last row's sort key.
    """

    data: list[T]
    next_cursor: str | None = None
