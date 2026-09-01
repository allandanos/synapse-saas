"""arq worker jobs.

Every job re-establishes TenantContext from explicit payload — contextvars do
not cross process/task boundaries by design.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from synapse_saas.core.db import get_session_factory
from synapse_saas.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

OUTBOX_BATCH = 20
DELIVERY_BATCH = 20


async def dispatch_outbox(ctx: dict[str, Any]) -> int:
    """Drain the outbox: fan out to webhook endpoints, mark published.

    Uses FOR UPDATE SKIP LOCKED so multiple workers never double-send.
    """
    from synapse_saas.audit.models import OutboxEvent
    from synapse_saas.webhooks.models import WebhookDelivery

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id FROM outbox_events
                        WHERE published_at IS NULL AND next_attempt_at <= now()
                        ORDER BY id
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"limit": OUTBOX_BATCH},
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0

        dispatched = 0
        for event_id in rows:
            event = await session.get(OutboxEvent, event_id)
            if event is None:
                continue

            # Fan out to matching endpoints
            if event.organization_id is not None:
                endpoints = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT id FROM webhook_endpoints
                                WHERE organization_id = :org AND is_active = true
                                """
                            ),
                            {"org": str(event.organization_id)},
                        )
                    )
                    .scalars()
                    .all()
                )
                for endpoint_id in endpoints:
                    session.add(
                        WebhookDelivery(
                            endpoint_id=endpoint_id,
                            organization_id=event.organization_id,
                            outbox_event_id=event.id,
                            event_type=event.event_type,
                            payload=dict(event.payload),
                        )
                    )

            event.published_at = datetime.now(UTC)
            dispatched += 1

        await session.commit()
        return dispatched


async def deliver_webhooks(ctx: dict[str, Any]) -> int:
    """Attempt pending deliveries whose backoff has elapsed."""
    from synapse_saas.webhooks.service import WebhookService

    factory = get_session_factory()
    async with factory() as session:
        due = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id FROM webhook_deliveries
                        WHERE status = 'pending' AND next_attempt_at <= now()
                        ORDER BY created_at
                        LIMIT :limit
                        """
                    ),
                    {"limit": DELIVERY_BATCH},
                )
            )
            .scalars()
            .all()
        )
        if not due:
            return 0

        service = WebhookService(session)
        delivered = 0
        for delivery_id in due:
            if await service.deliver(delivery_id):
                delivered += 1
        await session.commit()
        return delivered


async def rollup_usage(ctx: dict[str, Any]) -> int:
    """Hourly drift correction: rebuild current-period counters from events."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO usage_counters
                    (organization_id, metric, period_start, quantity_total, last_event_at)
                SELECT organization_id, metric, date_trunc('month', occurred_at)::date,
                       SUM(quantity), MAX(occurred_at)
                FROM usage_events
                WHERE occurred_at >= date_trunc('month', now())
                GROUP BY organization_id, metric, date_trunc('month', occurred_at)::date
                ON CONFLICT (organization_id, metric, period_start)
                DO UPDATE SET
                    quantity_total = EXCLUDED.quantity_total,
                    last_event_at = EXCLUDED.last_event_at
                """
            )
        )
        await session.commit()
        return 1


async def expire_entitlements(ctx: dict[str, Any]) -> int:
    """Mark lapsed grants revoked so entitlements stop resolving them."""
    from synapse_saas.core import events
    from synapse_saas.entitlements.models import Entitlement

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                        SELECT id, organization_id, feature_key
                        FROM entitlements
                        WHERE revoked_at IS NULL
                          AND ends_at IS NOT NULL
                          AND ends_at <= now()
                        """
                )
            )
        ).all()
        for row_id, org_id, feature_key in rows:
            entitlement = await session.get(Entitlement, row_id)
            if entitlement is None:
                continue
            entitlement.revoked_at = datetime.now(UTC)
            session.add(
                _outbox_row(
                    events.ENTITLEMENT_EXPIRED,
                    aggregate_type="entitlement",
                    aggregate_id=row_id,
                    organization_id=org_id,
                    payload={"feature_key": feature_key},
                )
            )
        await session.commit()
        return len(rows)


async def advance_manual_billing(ctx: dict[str, Any]) -> int:
    """Roll periods + issue invoices for manual-provider subscriptions."""
    from synapse_saas.billing.models import Invoice
    from synapse_saas.core import events as ev
    from synapse_saas.subscriptions.models import Subscription

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id FROM subscriptions
                        WHERE status = 'active'
                          AND provider = 'manual'
                          AND current_period_end <= now()
                          AND cancel_at_period_end = false
                        """
                    )
                )
            )
            .scalars()
            .all()
        )
        for subscription_id in rows:
            subscription = await session.get(Subscription, subscription_id)
            if subscription is None:
                continue
            snapshot = subscription.plan_snapshot or {}
            interval = timedelta(days=365 if snapshot.get("interval") == "year" else 30)
            subscription.current_period_start = subscription.current_period_end
            subscription.current_period_end = subscription.current_period_end + interval

            price = snapshot.get("price_cents")
            if price and price > 0:
                invoice = Invoice(
                    organization_id=subscription.organization_id,
                    billing_customer_id=subscription.billing_customer_id,
                    provider="manual",
                    currency=snapshot.get("currency", "PHP"),
                    subtotal_cents=price,
                    total_cents=price,
                    status="open",
                    period_start=subscription.current_period_start,
                    period_end=subscription.current_period_end,
                )
                session.add(invoice)
                await session.flush()
                session.add(
                    _outbox_row(
                        ev.INVOICE_CREATED,
                        aggregate_type="invoice",
                        aggregate_id=invoice.id,
                        organization_id=subscription.organization_id,
                        payload={"total_cents": price, "plan_key": snapshot.get("key")},
                    )
                )
        await session.commit()
        return len(rows)


async def ensure_partitions(ctx: dict[str, Any]) -> int:
    """Pre-create next month's usage_events partition."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                DO $$
                DECLARE
                    p DATE := (date_trunc('month', now()) + interval '1 month')::date;
                BEGIN
                    EXECUTE format(
                        'CREATE TABLE IF NOT EXISTS usage_events_y%sm%s PARTITION OF usage_events
                         FOR VALUES FROM (%L) TO (%L)',
                        to_char(p, 'YYYY'), to_char(p, 'MM'), p, p + INTERVAL '1 month'
                    );
                END $$;
                """
            )
        )
        await session.commit()
        return 1


async def purge_expired(ctx: dict[str, Any]) -> int:
    """Retention: old webhook deliveries (30d)."""

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM webhook_deliveries WHERE created_at < now() - interval '30 days'")
        )
        await session.commit()
        return 1


def _outbox_row(
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: Any,
    organization_id: Any,
    payload: dict[str, Any],
) -> Any:
    from synapse_saas.audit.models import OutboxEvent
    from synapse_saas.core.ids import uuid_v7

    return OutboxEvent(
        id=uuid_v7(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        organization_id=organization_id,
        event_type=event_type,
        payload=payload,
    )


def _redis_settings() -> object:
    """Map SYNAPSE_REDIS_URL onto arq's RedisSettings.

    arq doesn't read a URL; one env var configures app and worker alike.
    """
    from urllib.parse import urlparse

    from arq.connections import RedisSettings

    from synapse_saas.core.config import get_settings

    parsed = urlparse(get_settings().redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0) if parsed.path else 0,
    )


class WorkerSettings:
    """arq worker entrypoint. Crons keep the platform self-running."""

    functions: list[object] = [
        dispatch_outbox,
        deliver_webhooks,
        rollup_usage,
        expire_entitlements,
        advance_manual_billing,
        ensure_partitions,
        purge_expired,
    ]

    cron_jobs: list[object] = []  # populated by build_cron_jobs() below

    @staticmethod
    async def on_startup(ctx: dict[str, Any]) -> None:
        configure_logging()
        logger.info("worker_started")

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        from synapse_saas.billing.registry import close_http_client
        from synapse_saas.core.db import dispose_engine

        await close_http_client()
        await dispose_engine()
        logger.info("worker_stopped")


def build_cron_jobs() -> list[object]:
    from arq import cron

    return [
        cron(dispatch_outbox, second=set(range(0, 60, 5))),  # every 5s
        cron(deliver_webhooks, second=set(range(0, 60, 15))),  # every 15s
        cron(rollup_usage, minute=5, hour=None),  # hourly
        cron(expire_entitlements, minute=10, hour=None),  # hourly-ish
        cron(advance_manual_billing, minute=20, hour=None),  # hourly
        cron(ensure_partitions, minute=30, hour=3),  # daily
        cron(purge_expired, minute=40, hour=3),  # daily
    ]


WorkerSettings.redis_settings = _redis_settings()  # type: ignore[attr-defined]
WorkerSettings.cron_jobs = build_cron_jobs()
