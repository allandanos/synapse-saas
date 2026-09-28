"""Usage endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from synapse_saas.core.errors import ValidationFailedError
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.usage.schemas import (
    GaugeIn,
    UsageBatchIn,
    UsageCheckOut,
    UsageResultOut,
    UsageSummaryOut,
)
from synapse_saas.usage.service import UsageService

router = APIRouter(prefix="/usage", tags=["usage"])


@router.post("/events", response_model=list[UsageResultOut], status_code=status.HTTP_201_CREATED)
async def record_events(
    body: UsageBatchIn, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> list[UsageResultOut]:
    """Meter usage. Recording never blocks (soft path)."""
    service = UsageService(session)
    results = []
    for event in body.events:
        result = await service.record(
            tenant.organization_id,
            event.metric,
            quantity=event.quantity,
            idempotency_key=event.idempotency_key,
            properties=event.properties,
        )
        results.append(UsageResultOut(**result))
    return results


@router.post("/consume", response_model=UsageResultOut)
async def consume(
    body: UsageBatchIn, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> UsageResultOut:
    """Meter + enforce ONE event. 402 with upgrade hints on breach.

    More than one event is a 422 (it used to silently drop all but the first);
    use `/usage/consume-batch` for all-or-nothing batches.
    """
    if len(body.events) != 1:
        raise ValidationFailedError(
            "consume takes exactly one event; use /usage/consume-batch for batches",
            extras={"events": len(body.events), "batch_url": "/v1/usage/consume-batch"},
        )
    event = body.events[0]
    result = await UsageService(session).consume(
        tenant.organization_id,
        event.metric,
        quantity=event.quantity,
        idempotency_key=event.idempotency_key,
        properties=event.properties,
    )
    return UsageResultOut(**result)


@router.post("/consume-batch", response_model=list[UsageResultOut])
async def consume_batch(
    body: UsageBatchIn, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> list[UsageResultOut]:
    """Meter + enforce a batch atomically: the first breach 402s and NOTHING in
    the batch is counted (the request transaction rolls back)."""
    results = await UsageService(session).consume_many(
        tenant.organization_id, [event.model_dump() for event in body.events]
    )
    return [UsageResultOut(**r) for r in results]


@router.post("/gauge", response_model=UsageResultOut)
async def set_gauge(
    body: GaugeIn, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> UsageResultOut:
    """Set (`value`) or move (`delta`) a gauge metric — seats, projects, bytes.

    Gauges are levels, not flows: they never reset with the billing period and
    are never metered through /usage/events or /usage/consume. A positive
    `delta` is capacity-checked: **402** with upgrade hints when it would
    exceed the plan's cap, and the level is left untouched.
    """
    service = UsageService(session)
    if body.value is not None:
        result = await service.set_gauge(tenant.organization_id, body.metric, body.value)
    else:
        result = await service.adjust_gauge(tenant.organization_id, body.metric, body.delta or 0)
    return UsageResultOut(**result)


@router.get("/check", response_model=UsageCheckOut)
async def check_usage(
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
    metric: str = Query(),
    quantity: int = Query(1, ge=1),
) -> UsageCheckOut:
    result = await UsageService(session).check(tenant.organization_id, metric, quantity=quantity)
    return UsageCheckOut(**result)


@router.get("/summary", response_model=UsageSummaryOut)
async def usage_summary(
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
    period: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
) -> UsageSummaryOut:
    service = UsageService(session)
    from datetime import datetime

    period_date = datetime.strptime(period, "%Y-%m").date().replace(day=1) if period else None
    summary = await service.summary(tenant.organization_id, period=period_date)

    # One entitlement resolution for the whole summary (not one per metric)
    from synapse_saas.entitlements.service import EntitlementService

    entitlements = await EntitlementService(session).effective_for_org(tenant.organization_id)
    checks = []
    for entry in summary:
        check = service.check_against(entitlements, entry["metric"], used=entry["used"])
        checks.append(UsageCheckOut(**check))

    from datetime import UTC
    from datetime import datetime as dt

    from synapse_saas.usage.service import _month_bucket

    return UsageSummaryOut(
        period=(period_date or _month_bucket(dt.now(UTC))).isoformat(),
        metrics=checks,
    )
