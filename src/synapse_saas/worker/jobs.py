"""arq worker jobs.

Jobs run as the schema owner (`get_owner_session_factory`): they must see every
tenant and are never subject to row-level security.

Every job re-establishes TenantContext from explicit payload — contextvars do
not cross process/task boundaries by design.
"""

from __future__ import annotations

import contextlib
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from synapse_saas.core.db import get_owner_session_factory
from synapse_saas.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

OUTBOX_BATCH = 20
DELIVERY_BATCH = 20


async def dispatch_outbox(ctx: dict[str, Any]) -> int:
    """Drain the outbox: fan out to webhook endpoints, mark published.

    Uses FOR UPDATE SKIP LOCKED so multiple workers never double-send.
    """
    import time as _time

    _t0 = _time.perf_counter()
    try:
        result = await _dispatch_outbox_impl(ctx)
    except Exception:
        _record_job("dispatch_outbox", "error", _t0)
        raise
    else:
        _record_job("dispatch_outbox", "ok", _t0)
        return result


def _record_job(job: str, outcome: str, t0: float) -> None:
    with contextlib.suppress(Exception):  # metrics must never break a job
        from synapse_saas.core import metrics

        metrics.WORKER_JOBS.labels(job=job, outcome=outcome).inc()
        metrics.WORKER_JOB_LATENCY.labels(job=job).observe(time.perf_counter() - t0)


OUTBOX_MAX_ATTEMPTS = 8
OUTBOX_BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600, 3600, 3600)


async def _dispatch_outbox_impl(ctx: dict[str, Any]) -> int:
    """Per event, in its own savepoint:
    - public audience ⇒ one WebhookDelivery per active endpoint subscribed to
      the event type (empty `events` ⇒ all); internal audience never fans out
    - mark published
    On failure the savepoint rolls back, `attempts`/`last_error`/`next_attempt_at`
    are written, and after OUTBOX_MAX_ATTEMPTS the event is dead-lettered
    (`dead_at`) so one poison row cannot pin the batch forever.
    Emails run AFTER the commit — a retry can no longer resend them.
    """
    # Import order matters: these models FK cross-module (organizations, users).
    # A partial registry fails mapper configuration at query time — the worker's
    # lazy imports must land the whole graph before any ORM use.
    import synapse_saas.authorization.models
    import synapse_saas.identity.models
    import synapse_saas.tenancy.models  # noqa: F401
    from synapse_saas.audit.models import OutboxEvent
    from synapse_saas.core import events as ev
    from synapse_saas.webhooks.models import WebhookDelivery

    factory = get_owner_session_factory()
    to_email: list[tuple[str, dict[str, Any]]] = []
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id FROM outbox_events
                        WHERE published_at IS NULL AND dead_at IS NULL AND next_attempt_at <= now()
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
            try:
                async with session.begin_nested():
                    if event.audience == ev.AUDIENCE_PUBLIC and event.organization_id is not None:
                        endpoints = (
                            (
                                await session.execute(
                                    text(
                                        """
                                        SELECT id FROM webhook_endpoints
                                        WHERE organization_id = :org AND is_active = true
                                          AND (events = '{}' OR :event_type = ANY(events))
                                        """
                                    ),
                                    {"org": str(event.organization_id), "event_type": event.event_type},
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
                    await session.flush()
            except Exception as exc:
                _outbox_failure(event, exc)
                continue

            with contextlib.suppress(Exception):  # metrics must never block dispatch
                from synapse_saas.core import metrics

                metrics.BUSINESS_EVENTS.labels(event=event.event_type).inc()
            to_email.append((event.event_type, dict(event.payload)))
            dispatched += 1

        await session.commit()

    # In-process consumers run only after the events are durably published: a
    # crash or retry cannot send the same invite/invoice twice. Failures are
    # logged; the authz sync additionally re-queues itself on the next change.
    from synapse_saas.authorization import sync as authz_sync
    from synapse_saas.notifications.handlers import handle_event

    for event_type, payload in to_email:
        for consumer in (handle_event, authz_sync.handle_event):
            try:
                await consumer(event_type, payload)
            except Exception as exc:
                logger.warning(
                    "internal_consumer_failed",
                    consumer=consumer.__module__,
                    error=str(exc),
                    event_type=event_type,
                )
    return dispatched


def _outbox_failure(event: Any, exc: Exception) -> None:
    """Retry bookkeeping for one failed outbox event (savepoint already rolled back)."""
    event.attempts = int(event.attempts or 0) + 1
    event.last_error = str(exc)[:1000]
    if event.attempts >= OUTBOX_MAX_ATTEMPTS:
        event.dead_at = datetime.now(UTC)
        logger.error(
            "outbox_event_dead_lettered",
            event_id=str(event.id),
            event_type=event.event_type,
            attempts=event.attempts,
            error=event.last_error,
        )
        with contextlib.suppress(Exception):
            from synapse_saas.core import metrics

            metrics.OUTBOX_DEAD.labels(event=event.event_type).inc()
        return
    backoff = OUTBOX_BACKOFF_SECONDS[min(event.attempts - 1, len(OUTBOX_BACKOFF_SECONDS) - 1)]
    event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff)
    logger.warning(
        "outbox_event_failed",
        event_id=str(event.id),
        event_type=event.event_type,
        attempts=event.attempts,
        retry_in_seconds=backoff,
        error=event.last_error,
    )


async def deliver_webhooks(ctx: dict[str, Any]) -> int:
    """Attempt pending deliveries whose backoff has elapsed.

    Rows are claimed with SKIP LOCKED so N workers never POST the same delivery
    twice; the shared HTTP client (core/http.py) is reused across ticks.
    """
    from synapse_saas.core.http import get_http_client
    from synapse_saas.webhooks.service import WebhookService

    factory = get_owner_session_factory()
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
                        FOR UPDATE SKIP LOCKED
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

        service = WebhookService(session, http=get_http_client())
        delivered = 0
        for delivery_id in due:
            if await service.deliver(delivery_id):
                delivered += 1
        await session.commit()
        return delivered


async def rollup_usage(ctx: dict[str, Any]) -> int:
    """Hourly drift correction: rebuild current-period counters from events."""
    factory = get_owner_session_factory()
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

    factory = get_owner_session_factory()
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
        touched: set[str] = set()
        for row_id, org_id, feature_key in rows:
            entitlement = await session.get(Entitlement, row_id)
            if entitlement is None:
                continue
            entitlement.revoked_at = datetime.now(UTC)
            touched.add(str(org_id))
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
    # Invalidate AFTER commit so no reader caches the pre-revocation rows
    from synapse_saas.entitlements.service import invalidate_entitlements

    for org in touched:
        await invalidate_entitlements(org)
    return len(rows)


RENEWAL_BATCH = 100


async def advance_recurring_billing(ctx: dict[str, Any]) -> int:
    """Renew subscriptions WE bill: invoice the ended period, then roll it forward.

    Applies to every provider without `recurring_hosted` (manual, Xendit,
    PayMongo, …) — hosted providers (Stripe, …) renew on their side and report
    through webhooks. Rows are claimed with SKIP LOCKED so N workers never
    renew the same subscription twice; each renewal is its own savepoint so one
    bad subscription cannot block the batch. Invoices go through the invoicing
    engine (lines, number, overage, email) — never an inline Invoice(...).
    """
    from synapse_saas.billing.invoicing import InvoicingService
    from synapse_saas.billing.registry import locally_billed_provider_names
    from synapse_saas.subscriptions.models import Subscription

    local_providers = list(locally_billed_provider_names())
    factory = get_owner_session_factory()
    renewed = 0
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT id FROM subscriptions
                        WHERE status = 'active'
                          AND current_period_end <= now()
                          AND cancel_at_period_end = false
                          AND (provider IS NULL OR provider = ANY(:providers))
                        ORDER BY current_period_end
                        LIMIT :batch
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"providers": local_providers, "batch": RENEWAL_BATCH},
                )
            )
            .scalars()
            .all()
        )
        for subscription_id in rows:
            try:
                async with session.begin_nested():
                    subscription = await session.get(Subscription, subscription_id)
                    if subscription is None:
                        continue
                    await _renew_locally_billed(session, subscription, InvoicingService(session))
                    renewed += 1
            except Exception as exc:  # isolate one bad renewal, keep the batch
                logger.exception(
                    "recurring_billing_failed", subscription_id=str(subscription_id), error=str(exc)
                )
        await session.commit()
    return renewed


async def _renew_locally_billed(session: Any, subscription: Any, invoicing: Any) -> None:
    """Bill the period that just ended (in arrears: plan + overage + prorated
    corrections), then roll the period forward."""
    snapshot = subscription.plan_snapshot or {}
    ended_start = subscription.current_period_start
    price = int(snapshot.get("price_cents") or 0)
    if price > 0 or subscription.pending_adjustments:
        invoice = await invoicing.draft_for_org(
            subscription.organization_id, period=ended_start.date().replace(day=1)
        )
        if invoice.status == "draft":
            await invoicing.finalize(invoice.id, subscription.organization_id)

    interval = timedelta(days=365 if snapshot.get("interval") == "year" else 30)
    new_start = subscription.current_period_end
    subscription.current_period_start = new_start
    subscription.current_period_end = new_start + interval
    await session.flush()


# Kept as an alias for one release: the old name in cron configs/docs.
advance_manual_billing = advance_recurring_billing


PARTITION_MONTHS_AHEAD = 3


async def ensure_partitions(ctx: dict[str, Any]) -> int:
    """Pre-create usage_events partitions for the next PARTITION_MONTHS_AHEAD months.

    A lapsed run is survivable: rows for a month without a partition land in
    `usage_events_default` (migration 0016) instead of failing every insert.
    """
    factory = get_owner_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                """
                DO $$
                DECLARE
                    i INT;
                    p DATE;
                BEGIN
                    FOR i IN 0..:months LOOP
                        p := (date_trunc('month', now()) + make_interval(months => i))::date;
                        EXECUTE format(
                            'CREATE TABLE IF NOT EXISTS usage_events_y%sm%s PARTITION OF usage_events
                             FOR VALUES FROM (%L) TO (%L)',
                            to_char(p, 'YYYY'), to_char(p, 'MM'), p, p + INTERVAL '1 month'
                        );
                    END LOOP;
                END $$;
                """.replace(":months", str(PARTITION_MONTHS_AHEAD))
            )
        )
        await session.commit()
        return PARTITION_MONTHS_AHEAD + 1


IDEMPOTENCY_RETENTION_DAYS = 90
DELIVERY_RETENTION_DAYS = 30
EXHAUSTED_DELIVERY_RETENTION_DAYS = 90  # the failure audit trail outlives routine rows
OUTBOX_RETENTION_DAYS = 7


async def purge_expired(ctx: dict[str, Any]) -> int:
    """Retention: delivered/failed webhook deliveries (30d), exhausted ones (90d —
    they are the failure audit trail), published outbox rows (7d), spent usage
    idempotency keys (90d), audit logs past SYNAPSE_AUDIT_RETENTION_DAYS."""
    from synapse_saas.core.config import get_settings

    factory = get_owner_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "DELETE FROM webhook_deliveries WHERE status <> 'exhausted' "
                "AND created_at < now() - make_interval(days => :days)"
            ),
            {"days": DELIVERY_RETENTION_DAYS},
        )
        await session.execute(
            text(
                "DELETE FROM webhook_deliveries WHERE status = 'exhausted' "
                "AND created_at < now() - make_interval(days => :days)"
            ),
            {"days": EXHAUSTED_DELIVERY_RETENTION_DAYS},
        )
        await session.execute(
            text(
                "DELETE FROM outbox_events WHERE published_at IS NOT NULL "
                "AND published_at < now() - make_interval(days => :days)"
            ),
            {"days": OUTBOX_RETENTION_DAYS},
        )
        await session.execute(
            text("DELETE FROM audit_logs WHERE created_at < now() - make_interval(days => :days)"),
            {"days": get_settings().audit_retention_days},
        )
        # Presigned uploads never completed: give the reserved bytes back
        stale = (
            await session.execute(
                text(
                    "UPDATE stored_files SET deleted_at = now() "
                    "WHERE status = 'pending' AND deleted_at IS NULL "
                    "AND created_at < now() - make_interval(secs => :ttl) "
                    "RETURNING organization_id, size_bytes"
                ),
                {"ttl": get_settings().storage_presign_seconds * 2},
            )
        ).all()
        if stale:
            from synapse_saas.usage.service import UsageService

            usage = UsageService(session)
            for org_id, size_bytes in stale:
                await usage.adjust_gauge(org_id, "storage_bytes", -int(size_bytes), enforce=False)
        await session.execute(
            text(
                "DELETE FROM usage_idempotency_keys WHERE created_at < now() - make_interval(days => :days)"
            ),
            {"days": IDEMPOTENCY_RETENTION_DAYS},
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
        from synapse_saas.branding.loader import get_branding

        configure_logging()
        # Fail fast: emails and invoice PDFs render with it; a broken kit stops the worker.
        get_branding()
        logger.info("worker_started")

    @staticmethod
    async def on_shutdown(ctx: dict[str, Any]) -> None:
        from synapse_saas.core.db import dispose_engine
        from synapse_saas.core.http import close_http_client

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
        cron(advance_recurring_billing, minute=20, hour=None),  # hourly
        cron(ensure_partitions, minute=30, hour=3),  # daily
        cron(purge_expired, minute=40, hour=3),  # daily
    ]


WorkerSettings.redis_settings = _redis_settings()  # type: ignore[attr-defined]
WorkerSettings.cron_jobs = build_cron_jobs()
