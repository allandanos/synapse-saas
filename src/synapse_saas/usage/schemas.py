"""Usage API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UsageEventIn(BaseModel):
    metric: str
    quantity: int = Field(default=1, ge=1)
    idempotency_key: str | None = None
    properties: dict[str, Any] | None = None


class UsageBatchIn(BaseModel):
    events: list[UsageEventIn] = Field(min_length=1, max_length=100)


class UsageResultOut(BaseModel):
    metric: str
    quantity: int
    total: int
    limit: int | None = None
    remaining: int | None = None
    within_limit: bool | None = None


class UsageCheckOut(BaseModel):
    metric: str
    used: int
    limit: int | None
    remaining: int | None
    within_limit: bool
    soft_limit: int | None
    soft_limit_breached: bool


class UsageSummaryOut(BaseModel):
    period: str
    metrics: list[UsageCheckOut]
