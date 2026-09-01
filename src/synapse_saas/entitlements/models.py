"""Entitlement model: feature grants independent of the plan.

This table is what makes trials, add-ons, promos, grandfathering, beta access,
and enterprise overrides possible without touching application code. Plan
features are NOT materialized here — they're resolved at read time by the
entitlements resolver.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.core.db import Base, TenantMixin, TimestampMixin

ENTITLEMENT_SOURCES = ("trial", "addon", "promo", "beta", "override", "enterprise", "grandfather")

# Higher wins on conflict; a winning enabled=False grant removes a plan feature.
SOURCE_PRIORITY = {
    "plan": 0,
    "addon": 10,
    "beta": 20,
    "promo": 30,
    "grandfather": 40,
    "override": 50,
    "enterprise": 60,
}


class Entitlement(Base, TenantMixin, TimestampMixin):
    __tablename__ = "entitlements"
    __table_args__ = (
        CheckConstraint(
            "source IN ('trial','addon','promo','beta','override','enterprise','grandfather')",
            name="ck_entitlements_source",
        ),
        Index(
            "ix_entitlements_org_feature_active",
            "organization_id",
            "feature_key",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    feature_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # NULL ⇒ until revoked
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def priority(self) -> int:
        return SOURCE_PRIORITY.get(self.source, 0)

    @property
    def is_active(self) -> bool:
        now = datetime.now(UTC)
        return (
            self.revoked_at is None and self.starts_at <= now and (self.ends_at is None or now < self.ends_at)
        )
