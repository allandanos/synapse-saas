"""Usage API schemas."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


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
    # True when an idempotency_key matched an earlier request: nothing was counted again
    deduplicated: bool = False


class GaugeIn(BaseModel):
    """Set a gauge to `value`, or move it by `delta` — exactly one of the two."""

    metric: str
    value: int | None = Field(default=None, ge=0)
    delta: int | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        if (self.value is None) == (self.delta is None):
            raise ValueError("provide exactly one of value or delta")
        return self


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
