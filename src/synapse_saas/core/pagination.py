"""Pagination primitives shared by list endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


TOTAL_COUNT_HEADER = "X-Total-Count"


def page_params(
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(0, ge=0),
) -> PageParams:
    """FastAPI dependency: `?limit=&offset=` for every list route."""
    return PageParams(limit=limit, offset=offset)


PageDep = Annotated[PageParams, Depends(page_params)]


async def paginate(
    session: AsyncSession,
    stmt: Select[Any],
    params: PageParams,
    response: Response,
) -> Sequence[Any]:
    """Apply limit/offset to `stmt`, set `X-Total-Count` on the response, return the rows.

    Non-breaking by design: the body stays a plain list; the total rides a
    header (exposed through CORS) so existing clients keep working and
    paginating clients can render pages.
    """
    total = (
        await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = (await session.execute(stmt.limit(params.limit).offset(params.offset))).scalars().all()
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


def paginate_in_memory(items: Sequence[Any], params: PageParams, response: Response) -> list[Any]:
    """For small, already-loaded collections (service-built lists)."""
    response.headers[TOTAL_COUNT_HEADER] = str(len(items))
    return list(items[params.offset : params.offset + params.limit])
