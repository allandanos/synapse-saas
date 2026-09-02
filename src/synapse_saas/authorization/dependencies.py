"""Authorization dependencies.

`require_permission` is the router-facing gate: it takes the resolved tenant +
user, checks permission, and binds the enriched UserContext (with permission
keys) for downstream services and audit.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.authorization.service import AuthorizationService
from synapse_saas.core import context
from synapse_saas.core.context import TenantContext, UserContext
from synapse_saas.identity.dependencies import CurrentUser
from synapse_saas.identity.models import User
from synapse_saas.tenancy.dependencies import TenantDep


async def require_permission(
    permission: str,
    user: User,
    session: AsyncSession,
    tenant: TenantContext,
) -> None:
    """Check permission and bind the enriched user context. Raises 403 on deny.

    API-key principals authorize against the key's scopes instead of RBAC:
    an empty scope set means everything the creating user could exercise.
    """
    from synapse_saas.core import context as ctx_module

    principal = ctx_module.current_user()
    if principal is not None and principal.api_key_scopes is not None:
        scopes = principal.api_key_scopes
        allowed = permission in scopes if scopes else True
        if not allowed:
            from synapse_saas.core.errors import PermissionDeniedError

            raise PermissionDeniedError(
                f"API key lacks the {permission!r} scope",
                extras={"permission": permission, "auth": "api_key"},
            )
        return

    if user.is_platform_admin:
        context.set_user(
            UserContext(
                user_id=user.id,
                email=str(user.email),
                is_platform_admin=True,
                permission_keys=frozenset({"*"}),
            )
        )
        return

    authz = AuthorizationService(session)
    keys = await authz.permission_keys_for(user.id, tenant.organization_id)
    if permission not in keys:
        from synapse_saas.core.errors import PermissionDeniedError

        raise PermissionDeniedError(
            f"This action requires the {permission!r} permission",
            extras={"permission": permission},
        )
    context.set_user(
        UserContext(
            user_id=user.id,
            email=str(user.email),
            is_platform_admin=False,
            permission_keys=keys,
        )
    )


def permission_dependency(permission: str) -> Any:
    """FastAPI dependency factory: Depends(permission_dependency('member:invite'))."""

    async def _dependency(user: CurrentUser, tenant: TenantDep, session: AsyncSession) -> UserContext:
        await require_permission(permission, user, session, tenant)
        return context.require_user()

    return Annotated[UserContext, Depends(_dependency)]


async def require_feature_dependency(
    feature: str,
    user: CurrentUser,
    tenant: TenantDep,
    session: AsyncSession,
) -> UserContext:
    """Feature-gate dependency: Depends(require_feature('advanced_reports'))."""
    from synapse_saas.entitlements.service import EntitlementService

    await EntitlementService(session).require_feature(tenant.organization_id, feature)
    return context.require_user()


def require_feature(feature: str) -> Any:
    async def _dependency(user: CurrentUser, tenant: TenantDep, session: AsyncSession) -> UserContext:
        return await require_feature_dependency(feature, user, tenant, session)

    return Annotated[UserContext, Depends(_dependency)]
