"""Authorization dependencies.

`require_permission` is the router-facing gate: it takes the resolved tenant +
user, checks permission, and binds the enriched UserContext (with permission
keys) for downstream services and audit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.authorization.service import AuthorizationService
from synapse_saas.core import context
from synapse_saas.core.context import TenantContext, UserContext
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.identity.models import User
from synapse_saas.tenancy.dependencies import TenantDep


async def require_permission(
    permission: str,
    user: User,
    session: AsyncSession,
    tenant: TenantContext,
) -> None:
    """Check permission and bind the enriched user context. Raises 403 on deny.

    API-key principals authorize against the key's scopes, intersected with
    what the creating user can exercise RIGHT NOW: demoting or removing the
    creator shrinks (or kills) every key they minted. A key with no recorded
    creator is denied — there is nothing to bound it by.
    """
    from synapse_saas.core import context as ctx_module

    principal = ctx_module.current_user()
    if principal is not None and principal.api_key_scopes is not None:
        from synapse_saas.core.errors import PermissionDeniedError

        if permission not in principal.api_key_scopes:
            raise PermissionDeniedError(
                f"API key lacks the {permission!r} scope",
                extras={"permission": permission, "auth": "api_key"},
            )
        creator_id = principal.api_key_creator_id
        if creator_id is None:
            raise PermissionDeniedError(
                "API key has no recorded creator to bound its authority",
                extras={"permission": permission, "auth": "api_key", "reason": "unbounded_key"},
            )
        creator = await session.get(User, creator_id)
        if creator is None or not creator.is_active:
            raise PermissionDeniedError(
                "API key creator is no longer active",
                extras={"permission": permission, "auth": "api_key", "reason": "creator_inactive"},
            )
        if not creator.is_platform_admin:
            creator_keys = await AuthorizationService(session).permission_keys_for(
                creator_id, tenant.organization_id
            )
            if permission not in creator_keys:
                raise PermissionDeniedError(
                    f"API key creator no longer holds the {permission!r} permission",
                    extras={
                        "permission": permission,
                        "auth": "api_key",
                        "reason": "creator_lacks_permission",
                    },
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
    # UserContext always carries the RBAC keys (audit, API-key bounding);
    # the DECISION goes through user_can, which is RBAC or OpenFGA (ADR 0009).
    keys = await authz.permission_keys_for(user.id, tenant.organization_id)
    if not await authz.user_can(user.id, tenant.organization_id, permission):
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


def permission_dependency(permission: str) -> Callable[..., Awaitable[UserContext]]:
    """FastAPI dependency factory: `Depends(permission_dependency("member:invite"))`.

    Returns a plain async callable (not an `Annotated` alias) so it composes
    with `Depends`, router-level `dependencies=[...]`, and `Annotated[...]`.
    """

    async def _dependency(user: CurrentUser, tenant: TenantDep, session: SessionDep) -> UserContext:
        await require_permission(permission, user, session, tenant)
        return context.require_user()

    _dependency.__name__ = f"require_permission_{permission.replace(':', '_')}"
    return _dependency


def require_feature(feature: str) -> Callable[..., Awaitable[TenantContext]]:
    """Feature-gate dependency factory: `Depends(require_feature("advanced_reports"))`.

    Resolves the tenant (which binds the RLS tenant), then checks the org's
    effective entitlements; 403 with upgrade hints when the plan lacks it.
    """

    async def _dependency(user: CurrentUser, tenant: TenantDep, session: SessionDep) -> TenantContext:
        from synapse_saas.entitlements.service import EntitlementService

        await EntitlementService(session).require_feature(tenant.organization_id, feature)
        return tenant

    _dependency.__name__ = f"require_feature_{feature}"
    return _dependency
