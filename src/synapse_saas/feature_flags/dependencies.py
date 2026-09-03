"""Feature-flag router gate.

`Depends(require_flag("new-editor"))` → 403 `feature_flag_disabled` when off.
Distinct from `require_feature` (entitlements): flags gate code paths, not
paid tiers, so the failure carries the flag key instead of upgrade hints.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core.context import UserContext
from synapse_saas.core.errors import PermissionDeniedError
from synapse_saas.feature_flags.service import FeatureFlagService
from synapse_saas.identity.dependencies import CurrentUser
from synapse_saas.tenancy.dependencies import TenantDep


async def require_flag_dependency(
    flag_key: str,
    user: CurrentUser,
    tenant: TenantDep,
    session: AsyncSession,
) -> UserContext:
    from synapse_saas.core import context

    enabled = await FeatureFlagService(session).is_enabled(
        flag_key, organization_id=tenant.organization_id, user_id=user.id
    )
    if not enabled:
        raise PermissionDeniedError(
            f"This action requires the {flag_key!r} feature flag to be enabled",
            extras={"flag": flag_key, "reason": "feature_flag_disabled"},
        )
    return context.require_user()


def require_flag(flag_key: str) -> Any:
    async def _dependency(user: CurrentUser, tenant: TenantDep, session: AsyncSession) -> UserContext:
        return await require_flag_dependency(flag_key, user, tenant, session)

    return _dependency
