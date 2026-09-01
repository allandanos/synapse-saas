"""Subscription/plan API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlanFeatureRead(BaseModel):
    feature_key: str
    enabled: bool


class PlanLimitRead(BaseModel):
    metric: str
    limit_value: int | None
    soft_limit_ratio: float | None


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    price_cents: int | None
    currency: str
    interval: str | None
    is_public: bool
    is_custom: bool
    trial_days: int
    sort_order: int
    features: list[PlanFeatureRead] = []
    limits: list[PlanLimitRead] = []

    @field_validator("features", mode="before")
    @classmethod
    def _project_features(cls, v: object) -> object:
        # Plan.features holds PlanFeature ORM rows; project to the read shape
        if isinstance(v, (list, tuple)):
            return [
                {"feature_key": f.feature_key, "enabled": f.enabled} if hasattr(f, "feature_key") else f
                for f in v
            ]
        return v

    @field_validator("limits", mode="before")
    @classmethod
    def _project_limits(cls, v: object) -> object:
        if isinstance(v, (list, tuple)):
            return [
                {
                    "metric": pl.metric,
                    "limit_value": pl.limit_value,
                    "soft_limit_ratio": float(pl.soft_limit_ratio)
                    if pl.soft_limit_ratio is not None
                    else None,
                }
                if hasattr(pl, "metric")
                else pl
                for pl in v
            ]
        return v


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    plan_id: uuid.UUID
    plan: PlanRead
    status: str
    current_period_start: datetime
    current_period_end: datetime
    trial_ends_at: datetime | None
    cancel_at_period_end: bool
    canceled_at: datetime | None
    plan_snapshot: dict[str, Any]


class TrialStartRequest(BaseModel):
    plan_key: str = Field(min_length=1)


class PlanChangeRequest(BaseModel):
    plan_key: str = Field(min_length=1)


class CancelRequest(BaseModel):
    at_period_end: bool = True


class EffectiveEntitlementsRead(BaseModel):
    organization_id: uuid.UUID
    plan_key: str | None
    subscription_status: str | None
    features: list[str]
    limits: dict[str, dict[str, int | float | None]]
