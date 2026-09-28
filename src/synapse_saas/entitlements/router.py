"""Entitlement endpoints: effective set (tenant read) + grants (platform-operator only)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from synapse_saas.core.errors import EntitlementNotFoundError
from synapse_saas.entitlements.service import EntitlementService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.subscriptions.schemas import EffectiveEntitlementsRead
from synapse_saas.tenancy.dependencies import PlatformAdminDep, TenantDep

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
    # False ⇒ kill switch: a high-priority grant that REMOVES the feature
    enabled: bool = True
    duration_days: int | None = Field(None, ge=1, le=3650)
    note: str | None = None
    limit_value: int | None = Field(None, ge=0)


# ── Operator surface: grants are a platform action, never a tenant one ────────
# (A tenant holding entitlement:manage could grant itself `sso` or raise its own
# limits — so no tenant role has it, and these routes are PlatformAdminDep.)

admin_router = APIRouter(prefix="/admin/orgs/{org_id}/entitlements", tags=["admin"])


@admin_router.get("", response_model=EffectiveEntitlementsRead)
async def admin_effective_entitlements(
    org_id: UUID, platform: PlatformAdminDep, session: SessionDep
) -> EffectiveEntitlementsRead:
    effective = await EntitlementService(session).effective_for_org(org_id)
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


@admin_router.post("/grants", status_code=status.HTTP_201_CREATED)
async def admin_grant_entitlement(
    org_id: UUID, body: GrantRequest, platform: PlatformAdminDep, session: SessionDep, user: CurrentUser
) -> dict[str, Any]:
    entitlement = await EntitlementService(session).grant(
        org_id,
        feature_key=body.feature_key,
        source=body.source,
        enabled=body.enabled,
        duration_days=body.duration_days,
        note=body.note,
        limit_value=body.limit_value,
        created_by_user_id=user.id,
    )
    return {"id": str(entitlement.id), "feature_key": entitlement.feature_key, "source": entitlement.source}


@admin_router.delete("/grants/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_revoke_entitlement(
    org_id: UUID, grant_id: UUID, platform: PlatformAdminDep, session: SessionDep
) -> None:
    service = EntitlementService(session)
    entitlement = await service.get(grant_id)
    if entitlement.organization_id != org_id:
        raise EntitlementNotFoundError("Grant not found for this organization")
    await service.revoke(grant_id)
