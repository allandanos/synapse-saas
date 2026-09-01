"""Plan catalog and subscription models.

Money is integer minor units + ISO-4217 — never floats.
`plan_snapshot` freezes purchase-time price/features so YAML changes never
rewrite history (grandfathering).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from synapse_saas.core.db import Base, TimestampMixin


class Feature(Base):
    """Feature registry, synced from config/plans.yaml."""

    __tablename__ = "features"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Metric(Base):
    """Usage metric registry, synced from config/plans.yaml."""

    __tablename__ = "metrics"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("kind IN ('counter','gauge')", name="ck_metrics_kind"),
        nullable=False,
    )
    unit: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # NULL ⇒ custom / price-on-application (enterprise)
    price_cents: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="PHP", nullable=False)
    interval: Mapped[str | None] = mapped_column(
        String(10), CheckConstraint("interval IN ('month','year')", name="ck_plans_interval")
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # {"stripe": {"product_id": "...", "price_id": "..."}, "paymongo": {...}}
    provider_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_jsonb: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    features: Mapped[list[PlanFeature]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    limits: Mapped[list[PlanLimit]] = relationship(lazy="selectin", cascade="all, delete-orphan")

    @property
    def is_free(self) -> bool:
        return self.price_cents == 0


class PlanFeature(Base):
    __tablename__ = "plan_features"
    __table_args__ = (UniqueConstraint("plan_id", "feature_key", name="uq_plan_features"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(100), ForeignKey("features.key"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PlanLimit(Base):
    __tablename__ = "plan_limits"
    __table_args__ = (UniqueConstraint("plan_id", "metric", name="uq_plan_limits"),)

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    metric: Mapped[str] = mapped_column(String(100), ForeignKey("metrics.key"), primary_key=True)
    # NULL ⇒ unlimited
    limit_value: Mapped[int | None] = mapped_column(BigInteger)
    # e.g. 0.80 ⇒ warn at 80% consumption
    soft_limit_ratio: Mapped[float | None] = mapped_column(Numeric(5, 2))


class Subscription(Base, TimestampMixin):
    """One occupying subscription per org (partial unique below)."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trialing','active','past_due','canceled','incomplete','unpaid')",
            name="ck_subscriptions_status",
        ),
        Index(
            "uq_subscriptions_one_per_org",
            "organization_id",
            unique=True,
            postgresql_where=text("status IN ('trialing','active','past_due')"),
        ),
        Index(
            "uq_subscriptions_provider_ref",
            "provider",
            "provider_subscription_id",
            unique=True,
            postgresql_where=text("provider_subscription_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="trialing", nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255))
    billing_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_customers.id", ondelete="SET NULL")
    )
    plan_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_jsonb: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    plan: Mapped[Plan] = relationship(lazy="selectin")
