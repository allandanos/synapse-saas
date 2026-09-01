"""Usage metering service.

- `record`: metering never blocks — always succeeds (soft analytics path)
- `check`: read-only pre-flight against the effective limit
- `consume`: atomic increment + limit compare; breach rolls the whole
  transaction back (event + counter together) and raises 402
- `summary`/`limits`: console meters

Counter increments are one SQL statement (`INSERT ... ON CONFLICT DO UPDATE
... RETURNING`) so concurrent consumers can't overshoot without the breach
being detected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.errors import UnknownMetricError, UsageLimitExceededError
from synapse_saas.core.ids import uuid_v7
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.entitlements.service import EntitlementService

logger = get_logger(__name__)


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reads ───────────────────────────────────────────────────────────────────

    async def current_total(self, organization_id: UUID, metric: str, *, period: date | None = None) -> int:
        period_start = period or _month_bucket(datetime.now(UTC))
        row = (
            await self.session.execute(
                select(func.sum(text("quantity_total")))
                .select_from(text("usage_counters"))
                .where(
                    text("organization_id = :org"),
                    text("metric = :metric"),
                    text("period_start = :period"),
                ),
                {"org": str(organization_id), "metric": metric, "period": period_start},
            )
        ).scalar_one()
        return int(row or 0)

    async def summary(self, organization_id: UUID, *, period: date | None = None) -> list[dict[str, Any]]:
        period_start = period or _month_bucket(datetime.now(UTC))
        rows = (
            await self.session.execute(
                select(text("metric"), text("quantity_total"))
                .select_from(text("usage_counters"))
                .where(
                    text("organization_id = :org"),
                    text("period_start = :period"),
                ),
                {"org": str(organization_id), "period": period_start},
            )
        ).all()
        return [{"metric": r[0], "used": int(r[1] or 0)} for r in rows]

    async def check(self, organization_id: UUID, metric: str, *, quantity: int = 1) -> dict[str, Any]:
        """Read-only limit check for pre-flight UI."""
        entitlements = await EntitlementService(self.session).effective_for_org(organization_id)
        limit = entitlements.limit(metric)
        used = await self.current_total(organization_id, metric)
        value = limit.value if limit else None
        soft = int(value * limit.soft_limit_ratio) if (limit and value and limit.soft_limit_ratio) else None
        return {
            "metric": metric,
            "used": used,
            "limit": value,
            "remaining": (value - used) if value is not None else None,
            "within_limit": value is None or used + quantity <= value,
            "soft_limit": soft,
            "soft_limit_breached": soft is not None and used >= soft,
        }

    # ── Writes ──────────────────────────────────────────────────────────────────

    async def record(
        self,
        organization_id: UUID,
        metric: str,
        *,
        quantity: int = 1,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a usage event. Metering never blocks; no limit enforcement."""
        await self._assert_metric(metric)
        now = occurred_at or datetime.now(UTC)
        await self._insert_event(organization_id, metric, quantity, now, idempotency_key, properties)
        total = await self._increment_counter(organization_id, metric, quantity, now)
        await self._maybe_emit_soft_limit(organization_id, metric, total)
        return {"metric": metric, "quantity": quantity, "total": total}

    async def consume(
        self,
        organization_id: UUID,
        metric: str,
        *,
        quantity: int = 1,
        idempotency_key: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record + enforce. Breach raises UsageLimitExceededError (402) and the
        caller's transaction (event + counter) rolls back together."""
        await self._assert_metric(metric)
        now = datetime.now(UTC)

        entitlements = await EntitlementService(self.session).effective_for_org(organization_id)
        limit = entitlements.limit(metric)
        limit_value = limit.value if limit else None

        await self._insert_event(organization_id, metric, quantity, now, idempotency_key, properties)
        total = await self._increment_counter(organization_id, metric, quantity, now)

        if limit_value is not None and total > limit_value:
            raise UsageLimitExceededError(
                f"{metric} limit exceeded ({limit_value}/period)",
                extras={
                    "metric": metric,
                    "limit": limit_value,
                    "used": total - quantity,
                    "attempted": quantity,
                    "upgrade_url": "/dashboard/billing",
                },
            )

        await self._maybe_emit_soft_limit(organization_id, metric, total)
        if limit_value is not None and total >= limit_value:
            append_outbox(
                self.session,
                event_type=events.USAGE_HARD_LIMIT_REACHED,
                aggregate_type="usage",
                aggregate_id=uuid_v7(),
                organization_id=organization_id,
                payload={"metric": metric, "limit": limit_value, "total": total},
            )
        return {
            "metric": metric,
            "quantity": quantity,
            "total": total,
            "limit": limit_value,
            "remaining": (limit_value - total) if limit_value is not None else None,
            "within_limit": limit_value is None or total <= limit_value,
        }

    # ── Gauges ──────────────────────────────────────────────────────────────────

    async def ensure_gauge_capacity(
        self,
        organization_id: UUID,
        metric: str,
        *,
        current: int,
        adding: int = 1,
    ) -> None:
        """Gauge (capacity) check — e.g. seats. Caller holds the org-row lock."""
        await self._assert_metric(metric)
        entitlements = await EntitlementService(self.session).effective_for_org(organization_id)
        limit = entitlements.limit(metric)
        value = limit.value if limit else None
        if value is not None and current + adding > value:
            raise UsageLimitExceededError(
                f"{metric} limit reached ({value})",
                extras={
                    "metric": metric,
                    "limit": value,
                    "used": current,
                    "upgrade_url": "/dashboard/billing",
                },
            )

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _assert_metric(self, metric: str) -> None:
        from synapse_saas.subscriptions.models import Metric

        exists = (await self.session.execute(select(Metric).where(Metric.key == metric))).scalar_one_or_none()
        if exists is None:
            raise UnknownMetricError(f"Unknown usage metric {metric!r}", extras={"metric": metric})

    async def _insert_event(
        self,
        organization_id: UUID,
        metric: str,
        quantity: int,
        occurred_at: datetime,
        idempotency_key: str | None,
        properties: dict[str, Any] | None,
    ) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO usage_events
                    (id, organization_id, metric, quantity, occurred_at, idempotency_key, properties)
                VALUES
                    (:id, :org, :metric, :qty, :occurred, :idem, CAST(:props AS jsonb))
                """
            ),
            {
                "id": str(uuid_v7()),
                "org": str(organization_id),
                "metric": metric,
                "qty": quantity,
                "occurred": occurred_at,
                "idem": idempotency_key,
                "props": _json(properties or {}),
            },
        )

    async def _increment_counter(
        self, organization_id: UUID, metric: str, quantity: int, occurred_at: datetime
    ) -> int:
        """Atomic upsert-increment; returns the new total."""
        result = await self.session.execute(
            text(
                """
                INSERT INTO usage_counters
                    (organization_id, metric, period_start, quantity_total, last_event_at)
                VALUES (:org, :metric, :period, :qty, :occurred)
                ON CONFLICT (organization_id, metric, period_start)
                DO UPDATE SET
                    quantity_total = usage_counters.quantity_total + EXCLUDED.quantity_total,
                    last_event_at = EXCLUDED.last_event_at
                RETURNING quantity_total
                """
            ),
            {
                "org": str(organization_id),
                "metric": metric,
                "period": _month_bucket(occurred_at),
                "qty": quantity,
                "occurred": occurred_at,
            },
        )
        return int(result.scalar_one())

    async def _maybe_emit_soft_limit(self, organization_id: UUID, metric: str, total: int) -> None:
        """Emit usage.soft_limit_reached exactly once per metric per period."""
        entitlements = await EntitlementService(self.session).effective_for_org(organization_id)
        limit = entitlements.limit(metric)
        if not limit or limit.value is None or not limit.soft_limit_ratio:
            return
        threshold = int(limit.value * limit.soft_limit_ratio)
        if total < threshold:
            return

        row = (
            await self.session.execute(
                text(
                    """
                    UPDATE usage_counters
                    SET soft_limit_notified_at = now()
                    WHERE organization_id = :org
                      AND metric = :metric
                      AND period_start = :period
                      AND soft_limit_notified_at IS NULL
                    RETURNING 1
                    """
                ),
                {
                    "org": str(organization_id),
                    "metric": metric,
                    "period": _month_bucket(datetime.now(UTC)),
                },
            )
        ).scalar_one_or_none()
        if row is not None:
            append_outbox(
                self.session,
                event_type=events.USAGE_SOFT_LIMIT_REACHED,
                aggregate_type="usage",
                aggregate_id=uuid_v7(),
                organization_id=organization_id,
                payload={"metric": metric, "threshold": threshold, "total": total, "limit": limit.value},
            )


def _month_bucket(now: datetime) -> date:
    return now.date().replace(day=1)


def _json(props: dict) -> str:
    import json

    return json.dumps(props)
