"""Entitlement endpoints: effective set (read) + grants (admin)."""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.entitlements.service import EntitlementService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.subscriptions.schemas import EffectiveEntitlementsRead
from synapse_saas.tenancy.dependencies import TenantDep

router = APIRouter(tags=["entitlements"])


@router.get("/entitlements", response_model=EffectiveEntitlementsRead)
async def effective_entitlements(
    tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> EffectiveEntitlementsRead:
    effective = await EntitlementService(session).effective_for_org(tenant.organization_id)
    return EffectiveEntitlementsRead(
        organization_id=effective.organization_id,
        plan_key=effective.plan_key,
        subscription_status=effective.subscription_status,
        features=sorted(effective.features),
        limits={
            metric: {"value": lim.value, "soft_limit_ratio": lim.soft_limit_ratio}
            for metric, lim in effective.limits.items()
        },
    )


class GrantRequest(BaseModel):
    feature_key: str = Field(min_length=1)
    source: str = Field(pattern=r"^(trial|addon|promo|beta|override|enterprise|grandfather)$")
    duration_days: int | None = Field(None, ge=1, le=3650)
    note: str | None = None
    limit_value: int | None = Field(None, ge=0)


@router.post("/entitlements/grants", status_code=status.HTTP_201_CREATED)
async def grant_entitlement(
    body: GrantRequest, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> dict:
    await require_permission("entitlement:manage", user, session, tenant)
    entitlement = await EntitlementService(session).grant(
        tenant.organization_id,
        feature_key=body.feature_key,
        source=body.source,
        duration_days=body.duration_days,
        note=body.note,
        limit_value=body.limit_value,
        created_by_user_id=user.id,
    )
    return {"id": str(entitlement.id), "feature_key": entitlement.feature_key, "source": entitlement.source}
