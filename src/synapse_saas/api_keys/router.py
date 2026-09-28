"""API key endpoints (org-scoped)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from synapse_saas.api_keys.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from synapse_saas.api_keys.service import ApiKeyService
from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.authorization.permissions import PERMISSION_KEYS
from synapse_saas.core import context
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import TenantDep

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyRead])
async def list_keys(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> list[ApiKeyRead]:
    await require_permission("apikey:manage", user, session, tenant)
    keys = await ApiKeyService(session).list_keys(tenant.organization_id)
    return [ApiKeyRead.model_validate(k) for k in keys]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: ApiKeyCreate, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> ApiKeyCreated:
    await require_permission("apikey:manage", user, session, tenant)
    # Bound by the CREATOR: require_permission just bound the acting principal's
    # effective permissions (RBAC keys, "*" for platform admin, or the parent
    # key's scopes when a key mints a key).
    principal = context.require_user()
    creator_keys = PERMISSION_KEYS if "*" in principal.permission_keys else principal.permission_keys
    creator_id: UUID | None = user.id
    if principal.api_key_id is not None:
        # A key minting a key: root the chain at the human who created the parent
        # (require_permission already denied keys with no recorded creator).
        creator_id = principal.api_key_creator_id
    key, plaintext = await ApiKeyService(session).create_key(
        tenant.organization_id,
        name=body.name,
        scopes=body.scopes,
        expires_in_days=body.expires_in_days,
        created_by_user_id=creator_id,
        creator_keys=creator_keys,
    )
    base = ApiKeyRead.model_validate(key)
    return ApiKeyCreated(**base.model_dump(), key=plaintext)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> None:
    await require_permission("apikey:manage", user, session, tenant)
    await ApiKeyService(session).revoke_key(key_id, tenant.organization_id)
