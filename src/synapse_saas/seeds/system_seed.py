"""System seeds: permission catalog + system roles.

Idempotent — safe to run on every deploy. The plan catalog sync lives in
`subscriptions.sync` and runs alongside this from the CLI.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.authorization.models import AuthorizationRole, Permission, RolePermission
from synapse_saas.authorization.permissions import PERMISSIONS, SYSTEM_ROLES
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)


async def seed_system(session: AsyncSession) -> dict[str, int]:
    """Upsert permissions and system roles. Returns counts for logging."""
    # ── Permissions ─────────────────────────────────────────────────────────────
    existing_perms = {p.key: p for p in (await session.execute(select(Permission))).scalars()}
    for perm_def in PERMISSIONS:
        if perm_def.key in existing_perms:
            continue
        session.add(
            Permission(
                key=perm_def.key,
                resource=perm_def.resource,
                action=perm_def.action,
                description=perm_def.description,
            )
        )
    perm_count = len(PERMISSIONS)

    await session.flush()

    all_perms = {p.key: p for p in (await session.execute(select(Permission))).scalars()}

    # ── System roles ────────────────────────────────────────────────────────────
    from sqlalchemy.orm import selectinload

    existing_roles = {
        r.key: r
        for r in (
            await session.execute(
                select(AuthorizationRole)
                .options(selectinload(AuthorizationRole.permissions))
                .where(AuthorizationRole.is_system.is_(True))
            )
        ).scalars()
    }

    for role_key, definition in SYSTEM_ROLES.items():
        role = existing_roles.get(role_key)
        if role is None:
            role = AuthorizationRole(
                key=role_key,
                name=str(definition["name"]),
                description=str(definition["description"]),
                is_system=True,
                organization_id=None,
            )
            session.add(role)
            await session.flush()
            # Re-fetch with the relationship loaded for the permission diff below
            await session.refresh(role, attribute_names=["permissions"])
        elif "permissions" not in role.__dict__:
            await session.refresh(role, attribute_names=["permissions"])

        wanted_keys = set(definition["permissions"])  # type: ignore[arg-type]
        existing_role_perm_keys = {p.key for p in role.permissions}

        for key in wanted_keys - existing_role_perm_keys:
            session.add(RolePermission(role_id=role.id, permission_id=all_perms[key].id))
        # System role permissions are append-only in seed; removals are deliberate
        # catalog changes done by migration, not by re-seeding.

    role_count = len(SYSTEM_ROLES)
    logger.info("system_seeded", permissions=perm_count, system_roles=role_count)
    return {"permissions": perm_count, "system_roles": role_count}
