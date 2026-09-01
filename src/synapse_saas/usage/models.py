"""Usage metering models: events (partitioned) + current-period counters.

`usage_events` is declaratively partitioned by month on `occurred_at` (the
worker pre-creates future partitions). `usage_counters` is what limit checks
read — one row per (org, metric, month), incremented atomically.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.core.db import Base
from synapse_saas.core.ids import uuid_v7


class UsageEvent(Base):
    __abstract__ = True  # partitioned parent; partitions created by migration/worker

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid_v7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(100), ForeignKey("metrics.key"), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    metric: Mapped[str] = mapped_column(String(100), ForeignKey("metrics.key"), primary_key=True)
    # UTC month bucket, e.g. 2026-08-01
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    quantity_total: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    soft_limit_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"), nullable=False
    )
