"""Authorization service.

The OpenFGA seam: everything reads `AuthorizationService.user_can(...)`. Today
it's Postgres RBAC; an OpenFGA-backed implementation can replace it without
touching callers.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from synapse_saas.authorization.models import AuthorizationRole, MembershipRole, Permission, RolePermission
from synapse_saas.authorization.permissions import PERMISSION_KEYS
from synapse_saas.core.cache import VersionedCache
from synapse_saas.core.errors import PermissionDeniedError, RoleNotFoundError, SystemRoleImmutableError
from synapse_saas.core.logging import get_logger
from synapse_saas.tenancy.models import Membership

logger = get_logger(__name__)

_perm_cache = VersionedCache("perm", ttl=30)


class AuthorizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Checks ──────────────────────────────────────────────────────────────────

    async def permission_keys_for(self, user_id: UUID, organization_id: UUID) -> frozenset[str]:
        """Effective permission set for (user, org) — cached briefly."""
        cache_key = f"{user_id}:{organization_id}"
        cached = await _perm_cache.get(cache_key)
        if cached:
            return frozenset(cached.split(","))

        membership = (
            await self.session.execute(
                select(Membership).where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == user_id,
                    Membership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            keys: frozenset[str] = frozenset()
        else:
            keys = frozenset(membership.permission_keys or [])

        await _perm_cache.set(cache_key, ",".join(sorted(keys)))
        return keys

    async def user_can(self, user_id: UUID, organization_id: UUID, permission: str) -> bool:
        keys = await self.permission_keys_for(user_id, organization_id)
        return permission in keys

    async def require(self, user_id: UUID, organization_id: UUID, permission: str) -> None:
        if not await self.user_can(user_id, organization_id, permission):
            raise PermissionDeniedError(
                f"This action requires the {permission!r} permission",
                extras={"permission": permission},
            )

    # ── Role management ─────────────────────────────────────────────────────────

    async def list_roles(self, organization_id: UUID) -> list[AuthorizationRole]:
        result = await self.session.execute(
            select(AuthorizationRole)
            .options(selectinload(AuthorizationRole.permissions))
            .where(
                (AuthorizationRole.organization_id == organization_id)
                | (AuthorizationRole.organization_id.is_(None))
            )
            .order_by(AuthorizationRole.is_system.desc(), AuthorizationRole.key)
        )
        return list(result.scalars().all())

    async def create_custom_role(
        self,
        *,
        organization_id: UUID,
        key: str,
        name: str,
        description: str | None = None,
        permission_keys: list[str],
    ) -> AuthorizationRole:
        unknown = set(permission_keys) - PERMISSION_KEYS
        if unknown:
            raise PermissionDeniedError(
                f"Unknown permissions: {sorted(unknown)}", extras={"unknown": sorted(unknown)}
            )
        role = AuthorizationRole(
            organization_id=organization_id,
            key=key,
            name=name,
            description=description,
            is_system=False,
        )
        self.session.add(role)
        await self.session.flush()
        await self._set_role_permissions(role, permission_keys)
        # Response reads role.permissions; load it eagerly for the new object
        await self.session.refresh(role, attribute_names=["permissions"])
        return role

    async def update_custom_role(
        self,
        role_id: UUID,
        *,
        organization_id: UUID,
        name: str | None = None,
        description: str | None = None,
        permission_keys: list[str] | None = None,
    ) -> AuthorizationRole:
        role = await self._get_scoped_role(role_id, organization_id)
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if permission_keys is not None:
            unknown = set(permission_keys) - PERMISSION_KEYS
            if unknown:
                raise PermissionDeniedError(
                    f"Unknown permissions: {sorted(unknown)}", extras={"unknown": sorted(unknown)}
                )
            await self._set_role_permissions(role, permission_keys)
        await self.invalidate_org_perms(organization_id)
        return role

    async def delete_custom_role(self, role_id: UUID, *, organization_id: UUID) -> None:
        role = await self._get_scoped_role(role_id, organization_id)
        from sqlalchemy import delete

        await self.session.execute(delete(MembershipRole).where(MembershipRole.role_id == role_id))
        await self.session.delete(role)
        await self.invalidate_org_perms(organization_id)

    async def assign_role(self, membership: Membership, role_key: str) -> None:
        role = (
            await self.session.execute(
                select(AuthorizationRole)
                .options(selectinload(AuthorizationRole.permissions))
                .where(
                    AuthorizationRole.key == role_key,
                    (AuthorizationRole.organization_id == membership.organization_id)
                    | (AuthorizationRole.organization_id.is_(None)),
                )
            )
        ).scalar_one_or_none()
        if role is None:
            raise RoleNotFoundError(f"Role {role_key!r} not found")
        self.session.add(MembershipRole(membership_id=membership.id, role_id=role.id))
        membership.permission_keys = sorted({*membership.permission_keys, *(p.key for p in role.permissions)})
        if membership.user_id is not None:
            await self.invalidate_user_perms(membership.user_id, membership.organization_id)

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _get_scoped_role(self, role_id: UUID, organization_id: UUID) -> AuthorizationRole:
        role = await self.session.get(AuthorizationRole, role_id)
        if role is None or role.organization_id != organization_id:
            raise RoleNotFoundError("Role not found")
        if role.is_system:
            raise SystemRoleImmutableError("System roles cannot be modified")
        return role

    async def _set_role_permissions(self, role: AuthorizationRole, permission_keys: list[str]) -> None:
        from sqlalchemy import delete

        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        perms = (
            (await self.session.execute(select(Permission).where(Permission.key.in_(permission_keys))))
            .scalars()
            .all()
        )
        for perm in perms:
            self.session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await self.session.flush()
        # Refresh denormalized membership.permission_keys for members holding this role
        await self._refresh_memberships_for_role(role)

    async def _refresh_memberships_for_role(self, role: AuthorizationRole) -> None:
        memberships = (
            (
                await self.session.execute(
                    select(Membership)
                    .join(MembershipRole, MembershipRole.membership_id == Membership.id)
                    .where(MembershipRole.role_id == role.id)
                )
            )
            .scalars()
            .all()
        )
        for membership in memberships:
            await self.recompute_membership_permissions(membership)

    async def recompute_membership_permissions(self, membership: Membership) -> None:
        roles = (
            (
                await self.session.execute(
                    select(AuthorizationRole)
                    .options(selectinload(AuthorizationRole.permissions))
                    .join(MembershipRole, MembershipRole.role_id == AuthorizationRole.id)
                    .where(MembershipRole.membership_id == membership.id)
                )
            )
            .scalars()
            .all()
        )
        membership.permission_keys = sorted({p.key for r in roles for p in r.permissions})

    async def invalidate_user_perms(self, user_id: UUID, organization_id: UUID) -> None:
        """Drop the cached permission set for one (user, org) pair.

        Role/membership changes must be visible to the very next request.
        """
        await _perm_cache.bump(f"{user_id}:{organization_id}")

    async def invalidate_org_perms(self, organization_id: UUID) -> None:
        """Invalidate every member of an org (role edits, custom-role changes)."""
        memberships = (
            (
                await self.session.execute(
                    select(Membership.user_id).where(
                        Membership.organization_id == organization_id,
                        Membership.user_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in memberships:
            if user_id is not None:
                await self.invalidate_user_perms(user_id, organization_id)
