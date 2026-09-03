"""Feature flag endpoints.

Management (create/update/overrides) is platform-admin; evaluation is a cheap
org-scoped check any authenticated member can call.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from synapse_saas.feature_flags.schemas import (
    FlagCheck,
    FlagCreate,
    FlagRead,
    FlagUpdate,
    OverrideCreate,
    OverrideRead,
)
from synapse_saas.feature_flags.service import FeatureFlagService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import PlatformAdminDep, TenantDep

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


# ── Management (platform admin) ────────────────────────────────────────────────


@router.get("", response_model=list[FlagRead])
async def list_flags(platform: PlatformAdminDep, session: SessionDep) -> list[FlagRead]:
    return [FlagRead.model_validate(f) for f in await FeatureFlagService(session).list_flags()]


@router.post("", response_model=FlagRead, status_code=status.HTTP_201_CREATED)
async def create_flag(body: FlagCreate, platform: PlatformAdminDep, session: SessionDep) -> FlagRead:
    flag = await FeatureFlagService(session).create_flag(
        key=body.key,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        rollout_percentage=body.rollout_percentage,
    )
    return FlagRead.model_validate(flag)


@router.patch("/{key}", response_model=FlagRead)
async def update_flag(
    key: str, body: FlagUpdate, platform: PlatformAdminDep, session: SessionDep
) -> FlagRead:
    flag = await FeatureFlagService(session).update_flag(
        key, enabled=body.enabled, rollout_percentage=body.rollout_percentage
    )
    return FlagRead.model_validate(flag)


@router.get("/{key}/overrides", response_model=list[OverrideRead])
async def list_overrides(key: str, platform: PlatformAdminDep, session: SessionDep) -> list[OverrideRead]:
    overrides = await FeatureFlagService(session).list_overrides(key)
    return [OverrideRead.model_validate(o) for o in overrides]


@router.post("/{key}/overrides", response_model=OverrideRead, status_code=status.HTTP_201_CREATED)
async def set_override(
    key: str, body: OverrideCreate, platform: PlatformAdminDep, session: SessionDep
) -> OverrideRead:
    override = await FeatureFlagService(session).set_override(
        key,
        organization_id=body.organization_id,
        user_id=body.user_id,
        enabled=body.enabled,
        note=body.note,
    )
    return OverrideRead.model_validate(override)


@router.delete("/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(override_id: UUID, platform: PlatformAdminDep, session: SessionDep) -> None:
    await FeatureFlagService(session).delete_override(override_id)


# ── Evaluation (org-scoped) ────────────────────────────────────────────────────


@router.get("/check/{key}", response_model=FlagCheck)
async def check_flag(key: str, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> FlagCheck:
    """Resolve a flag for the caller's org + user (overrides + rollout aware)."""
    enabled = await FeatureFlagService(session).is_enabled(
        key, organization_id=tenant.organization_id, user_id=user.id
    )
    return FlagCheck(key=key, enabled=enabled)
