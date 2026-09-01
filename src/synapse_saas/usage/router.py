"""Usage endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.usage.schemas import (
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
    """Meter + enforce. 402 with upgrade hints on breach."""
    event = body.events[0]
    result = await UsageService(session).consume(
        tenant.organization_id,
        event.metric,
        quantity=event.quantity,
        idempotency_key=event.idempotency_key,
        properties=event.properties,
    )
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
    period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
) -> UsageSummaryOut:
    service = UsageService(session)
    from datetime import datetime

    period_date = datetime.strptime(period, "%Y-%m").date().replace(day=1) if period else None
    summary = await service.summary(tenant.organization_id, period=period_date)

    checks = []
    for entry in summary:
        check = await service.check(tenant.organization_id, entry["metric"])
        checks.append(UsageCheckOut(**{**check, "used": entry["used"]}))

    from datetime import UTC
    from datetime import datetime as dt

    from synapse_saas.usage.service import _month_bucket

    return UsageSummaryOut(
        period=(period_date or _month_bucket(dt.now(UTC))).isoformat(),
        metrics=checks,
    )
