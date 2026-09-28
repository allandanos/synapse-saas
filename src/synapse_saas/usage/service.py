"""Usage metering service.

- `record`: metering never blocks — always succeeds (soft analytics path)
- `check`: read-only pre-flight against the effective limit
- `consume`: atomic increment + limit compare; breach rolls the whole
  transaction back (event + counter together) and raises 402
- `summary`/`limits`: console meters

Counter increments are one SQL statement (`INSERT ... ON CONFLICT DO UPDATE
... RETURNING`) so concurrent consumers can't overshoot without the breach
being detected.

Idempotency: an `idempotency_key` is reserved in `usage_idempotency_keys`
(primary key per org) BEFORE the event is written. A retry — even a concurrent
one — blocks on that row until the first request commits, then reads the stored
result back instead of counting again. A breached `consume` rolls the
reservation back with everything else, so the retry re-attempts (and 402s again).

Gauges (`kind: gauge` metrics — seats, projects, bytes stored) are levels, not
flows: `set_gauge` / `adjust_gauge` write the level into a fixed bucket that
never resets with the month; `record`/`consume` reject gauge metrics.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.errors import UnknownMetricError, UsageLimitExceededError, ValidationFailedError
from synapse_saas.core.ids import uuid_v7
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.entitlements.service import EntitlementService

logger = get_logger(__name__)

# Gauges live in one fixed period bucket: a level has no month to reset with.
GAUGE_PERIOD = date(1970, 1, 1)


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reads ───────────────────────────────────────────────────────────────────

    async def current_total(self, organization_id: UUID, metric: str, *, period: date | None = None) -> int:
        period_start = period or await self._period_for(metric)
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
                    text("(period_start = :period OR period_start = :gauge_period)"),
                ),
                {"org": str(organization_id), "period": period_start, "gauge_period": GAUGE_PERIOD},
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
        await self._assert_counter_metric(metric)
        if idempotency_key is not None and not await self._reserve_idempotency(
            organization_id, idempotency_key, metric, quantity
        ):
            return await self._replay_idempotent(organization_id, idempotency_key)
        now = occurred_at or datetime.now(UTC)
        event_id = await self._insert_event(
            organization_id, metric, quantity, now, idempotency_key, properties
        )
        total = await self._increment_counter(organization_id, metric, quantity, now)
        await self._maybe_emit_soft_limit(organization_id, metric, total)
        if idempotency_key is not None:
            await self._settle_idempotency(organization_id, idempotency_key, event_id, total)
        return {"metric": metric, "quantity": quantity, "total": total, "deduplicated": False}

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
        caller's transaction (event + counter + idempotency reservation) rolls
        back together."""
        await self._assert_counter_metric(metric)
        now = datetime.now(UTC)

        entitlements = await EntitlementService(self.session).effective_for_org(organization_id)
        limit = entitlements.limit(metric)
        limit_value = limit.value if limit else None

        if idempotency_key is not None and not await self._reserve_idempotency(
            organization_id, idempotency_key, metric, quantity
        ):
            replay = await self._replay_idempotent(organization_id, idempotency_key)
            replay["limit"] = limit_value
            replay["remaining"] = (limit_value - replay["total"]) if limit_value is not None else None
            replay["within_limit"] = limit_value is None or replay["total"] <= limit_value
            return replay

        event_id = await self._insert_event(
            organization_id, metric, quantity, now, idempotency_key, properties
        )
        total = await self._increment_counter(organization_id, metric, quantity, now)

        if limit_value is not None and total > limit_value:
            _inc_limited(metric)
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
        if idempotency_key is not None:
            await self._settle_idempotency(organization_id, idempotency_key, event_id, total)
        return {
            "metric": metric,
            "quantity": quantity,
            "total": total,
            "limit": limit_value,
            "remaining": (limit_value - total) if limit_value is not None else None,
            "within_limit": limit_value is None or total <= limit_value,
            "deduplicated": False,
        }

    async def consume_many(
        self, organization_id: UUID, events_in: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Consume a batch atomically: the first breach raises and the caller's
        transaction rolls back every event in the batch (all-or-nothing)."""
        return [
            await self.consume(
                organization_id,
                str(event["metric"]),
                quantity=int(event.get("quantity", 1)),
                idempotency_key=event.get("idempotency_key"),
                properties=event.get("properties"),
            )
            for event in events_in
        ]

    # ── Gauges ──────────────────────────────────────────────────────────────────

    async def set_gauge(self, organization_id: UUID, metric: str, value: int) -> dict[str, Any]:
        """Set a gauge to an absolute level (seats in use, projects, bytes stored)."""
        await self._assert_gauge_metric(metric)
        level = max(int(value), 0)
        await self.session.execute(
            text(
                """
                INSERT INTO usage_counters
                    (organization_id, metric, period_start, quantity_total, last_event_at)
                VALUES (:org, :metric, :period, :level, now())
                ON CONFLICT (organization_id, metric, period_start)
                DO UPDATE SET quantity_total = EXCLUDED.quantity_total, last_event_at = now()
                """
            ),
            {"org": str(organization_id), "metric": metric, "period": GAUGE_PERIOD, "level": level},
        )
        return await self._gauge_result(organization_id, metric, level)

    async def adjust_gauge(
        self, organization_id: UUID, metric: str, delta: int, *, enforce: bool = True
    ) -> dict[str, Any]:
        """Move a gauge by `delta` (never below zero); returns the new level.

        A positive delta is capacity-checked first (402 with upgrade hints when
        it would exceed the limit) unless `enforce=False` — the one-call shape
        for "add a seat / project / upload": check, then move, in one transaction.
        """
        await self._assert_gauge_metric(metric)
        if enforce and delta > 0:
            current = await self.current_total(organization_id, metric)
            await self.ensure_gauge_capacity(organization_id, metric, current=current, adding=delta)
        level = (
            await self.session.execute(
                text(
                    """
                    INSERT INTO usage_counters
                        (organization_id, metric, period_start, quantity_total, last_event_at)
                    VALUES (:org, :metric, :period, GREATEST(:delta, 0), now())
                    ON CONFLICT (organization_id, metric, period_start)
                    DO UPDATE SET
                        quantity_total = GREATEST(usage_counters.quantity_total + EXCLUDED.quantity_total
                                                  - GREATEST(:delta, 0) + :delta, 0),
                        last_event_at = now()
                    RETURNING quantity_total
                    """
                ),
                {"org": str(organization_id), "metric": metric, "period": GAUGE_PERIOD, "delta": int(delta)},
            )
        ).scalar_one()
        return await self._gauge_result(organization_id, metric, int(level))

    async def _gauge_result(self, organization_id: UUID, metric: str, level: int) -> dict[str, Any]:
        entitlements = await EntitlementService(self.session).effective_for_org(organization_id)
        limit = entitlements.limit(metric)
        value = limit.value if limit else None
        return {
            "metric": metric,
            "quantity": level,
            "total": level,
            "limit": value,
            "remaining": (value - level) if value is not None else None,
            "within_limit": value is None or level <= value,
            "deduplicated": False,
        }

    async def ensure_gauge_capacity(
        self,
        organization_id: UUID,
        metric: str,
        *,
        current: int,
        adding: int = 1,
    ) -> None:
        """Gauge (capacity) check — e.g. seats. Caller holds the org-row lock."""
        await self._assert_gauge_metric(metric)
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

    async def _metric(self, metric: str) -> Any:
        from synapse_saas.subscriptions.models import Metric

        row = (await self.session.execute(select(Metric).where(Metric.key == metric))).scalar_one_or_none()
        if row is None:
            raise UnknownMetricError(f"Unknown usage metric {metric!r}", extras={"metric": metric})
        return row

    async def _assert_counter_metric(self, metric: str) -> None:
        row = await self._metric(metric)
        if row.kind == "gauge":
            raise ValidationFailedError(
                f"{metric!r} is a gauge (a level, not a flow): set it with POST /usage/gauge",
                extras={"metric": metric, "kind": "gauge"},
            )

    async def _assert_gauge_metric(self, metric: str) -> None:
        row = await self._metric(metric)
        if row.kind != "gauge":
            raise ValidationFailedError(
                f"{metric!r} is a counter: meter it with /usage/events or /usage/consume",
                extras={"metric": metric, "kind": row.kind},
            )

    async def _period_for(self, metric: str) -> date:
        row = await self._metric(metric)
        return GAUGE_PERIOD if row.kind == "gauge" else _month_bucket(datetime.now(UTC))

    async def _reserve_idempotency(self, organization_id: UUID, key: str, metric: str, quantity: int) -> bool:
        """True ⇒ first sight of this key (the caller proceeds); False ⇒ replay."""
        row = (
            await self.session.execute(
                text(
                    """
                    INSERT INTO usage_idempotency_keys (organization_id, idempotency_key, metric, quantity)
                    VALUES (:org, :key, :metric, :qty)
                    ON CONFLICT (organization_id, idempotency_key) DO NOTHING
                    RETURNING 1
                    """
                ),
                {"org": str(organization_id), "key": key, "metric": metric, "qty": quantity},
            )
        ).scalar_one_or_none()
        return row is not None

    async def _settle_idempotency(self, organization_id: UUID, key: str, event_id: UUID, total: int) -> None:
        await self.session.execute(
            text(
                """
                UPDATE usage_idempotency_keys SET event_id = :event_id, total_after = :total
                WHERE organization_id = :org AND idempotency_key = :key
                """
            ),
            {"org": str(organization_id), "key": key, "event_id": str(event_id), "total": total},
        )

    async def _replay_idempotent(self, organization_id: UUID, key: str) -> dict[str, Any]:
        row = (
            await self.session.execute(
                text(
                    """
                    SELECT metric, quantity, total_after FROM usage_idempotency_keys
                    WHERE organization_id = :org AND idempotency_key = :key
                    """
                ),
                {"org": str(organization_id), "key": key},
            )
        ).one()
        logger.info("usage_deduplicated", org=str(organization_id), idempotency_key=key, metric=row.metric)
        return {
            "metric": str(row.metric),
            "quantity": int(row.quantity),
            "total": int(row.total_after or 0),
            "deduplicated": True,
        }

    async def _insert_event(
        self,
        organization_id: UUID,
        metric: str,
        quantity: int,
        occurred_at: datetime,
        idempotency_key: str | None,
        properties: dict[str, Any] | None,
    ) -> UUID:
        event_id = uuid_v7()
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
                "id": str(event_id),
                "org": str(organization_id),
                "metric": metric,
                "qty": quantity,
                "occurred": occurred_at,
                "idem": idempotency_key,
                "props": _json(properties or {}),
            },
        )
        return event_id

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
                payload={
                    "organization_id": str(organization_id),
                    "metric": metric,
                    "threshold": threshold,
                    "total": total,
                    "limit": limit.value,
                },
            )


def _month_bucket(now: datetime) -> date:
    return now.date().replace(day=1)


def _json(props: dict[str, Any]) -> str:
    import json

    return json.dumps(props)


def _inc_limited(metric: str) -> None:
    with contextlib.suppress(Exception):  # metrics must never fail the operation
        from synapse_saas.core import metrics

        metrics.USAGE_LIMITED.labels(metric=metric).inc()
