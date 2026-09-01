"""Plan + subscription endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.entitlements.service import EntitlementService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.subscriptions.schemas import (
    CancelRequest,
    EffectiveEntitlementsRead,
    PlanChangeRequest,
    PlanRead,
    SubscriptionRead,
    TrialStartRequest,
)
from synapse_saas.subscriptions.service import SubscriptionService
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.usage.service import UsageService

router = APIRouter(tags=["subscriptions"])


@router.get("/plans", response_model=list[PlanRead])
async def list_plans(session: SessionDep, user: CurrentUser) -> list[PlanRead]:
    from sqlalchemy import select

    from synapse_saas.subscriptions.models import Plan

    plans = (
        (
            await session.execute(
                select(Plan)
                .where(Plan.is_public.is_(True), Plan.archived_at.is_(None))
                .order_by(Plan.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return [PlanRead.model_validate(p) for p in plans]


@router.get("/subscription")
async def current_subscription(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> dict:
    await require_permission("billing:read", user, session, tenant)
    subscriptions = SubscriptionService(session)
    subscription = await subscriptions.current_for_org(tenant.organization_id)
    entitlements = await EntitlementService(session).effective_for_org(tenant.organization_id)
    usage = await UsageService(session).summary(tenant.organization_id)

    return {
        "subscription": SubscriptionRead.model_validate(subscription) if subscription else None,
        "entitlements": EffectiveEntitlementsRead(
            organization_id=entitlements.organization_id,
            plan_key=entitlements.plan_key,
            subscription_status=entitlements.subscription_status,
            features=sorted(entitlements.features),
            limits={
                metric: {"value": lim.value, "soft_limit_ratio": lim.soft_limit_ratio}
                for metric, lim in entitlements.limits.items()
            },
        ),
        "usage": usage,
    }


@router.post("/subscription/trial", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
async def start_trial(
    body: TrialStartRequest, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> SubscriptionRead:
    await require_permission("billing:manage", user, session, tenant)
    subscription = await SubscriptionService(session).start_trial(
        tenant.organization_id, plan_key=body.plan_key
    )
    return SubscriptionRead.model_validate(subscription)


@router.post("/subscription/change", response_model=SubscriptionRead)
async def change_plan(
    body: PlanChangeRequest, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> SubscriptionRead:
    await require_permission("billing:manage", user, session, tenant)
    subscription = await SubscriptionService(session).change_plan(
        tenant.organization_id, plan_key=body.plan_key
    )
    return SubscriptionRead.model_validate(subscription)


@router.post("/subscription/cancel", response_model=SubscriptionRead)
async def cancel_subscription(
    body: CancelRequest, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> SubscriptionRead:
    await require_permission("billing:manage", user, session, tenant)
    subscription = await SubscriptionService(session).cancel(
        tenant.organization_id, at_period_end=body.at_period_end
    )
    return SubscriptionRead.model_validate(subscription)


@router.post("/subscription/resume", response_model=SubscriptionRead)
async def resume_subscription(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> SubscriptionRead:
    await require_permission("billing:manage", user, session, tenant)
    subscription = await SubscriptionService(session).resume(tenant.organization_id)
    return SubscriptionRead.model_validate(subscription)
