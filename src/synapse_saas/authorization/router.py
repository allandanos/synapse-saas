"""Role + permission endpoints (org-scoped)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from synapse_saas.authorization.schemas import PermissionRead, RoleCreate, RoleRead, RoleUpdate
from synapse_saas.authorization.service import AuthorizationService
from synapse_saas.core.context import TenantContext
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.identity.models import User
from synapse_saas.tenancy.dependencies import TenantDep

router = APIRouter(tags=["roles"])


def _role_read(role) -> RoleRead:  # type: ignore[no-untyped-def]
    read = RoleRead.model_validate(role)
    if "permissions" in role.__dict__:
        read.permissions = sorted(p.key for p in role.permissions)
    return read


async def _require(permission: str, user: User, tenant: TenantContext, session: SessionDep) -> None:
    from synapse_saas.authorization.dependencies import require_permission

    await require_permission(permission, user, session, tenant)


@router.get("/roles")
async def list_roles(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> list[RoleRead]:
    await _require("member:read", user, tenant, session)
    roles = await AuthorizationService(session).list_roles(tenant.organization_id)
    return [_role_read(r) for r in roles]


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> RoleRead:
    await _require("role:manage", user, tenant, session)
    service = AuthorizationService(session)
    role = await service.create_custom_role(
        organization_id=tenant.organization_id,
        key=body.key,
        name=body.name,
        description=body.description,
        permission_keys=body.permissions,
    )
    return _role_read(role)


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: UUID, body: RoleUpdate, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> RoleRead:
    await _require("role:manage", user, tenant, session)
    service = AuthorizationService(session)
    role = await service.update_custom_role(
        role_id,
        organization_id=tenant.organization_id,
        name=body.name,
        description=body.description,
        permission_keys=body.permissions,
    )
    return _role_read(role)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> None:
    await _require("role:manage", user, tenant, session)
    await AuthorizationService(session).delete_custom_role(role_id, organization_id=tenant.organization_id)


@router.get("/permissions")
async def list_permissions() -> list[PermissionRead]:
    from synapse_saas.authorization.permissions import PERMISSIONS

    return [
        PermissionRead(key=p.key, resource=p.resource, action=p.action, description=p.description)
        for p in PERMISSIONS
    ]
