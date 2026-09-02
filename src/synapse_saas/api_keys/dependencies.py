"""API-key authentication dependency.

An `sk_…` bearer authenticates as the key's organization. The dependency binds:
- UserContext with the key's id + scopes (permission checks consult scopes)
- TenantContext pinned to the key's org (no X-Org-Id needed or honored)

Revoked/expired/unknown keys all return the same opaque 401 — the caller learns
nothing about which condition failed.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.api_keys.models import ApiKey
from synapse_saas.api_keys.service import KEY_PREFIX, ApiKeyService
from synapse_saas.core import context
from synapse_saas.core.context import TenantContext, UserContext
from synapse_saas.core.errors import AuthenticationError
from synapse_saas.core.logging import get_logger
from synapse_saas.tenancy.models import Organization

logger = get_logger(__name__)


async def try_api_key_auth(request: Request, session: AsyncSession) -> ApiKey | None:
    """Resolve an `sk_` bearer to its key row, or None when not a key request."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.removeprefix("Bearer ")
    if not token.startswith(KEY_PREFIX):
        return None
    key = await ApiKeyService(session).verify(token)
    if key is None:
        raise AuthenticationError("Invalid API key")
    return key


def bind_api_key_context(key: ApiKey, org: Organization) -> None:
    """Bind tenant + actor context for a key-authenticated request."""
    context.set_tenant(TenantContext(organization_id=key.organization_id, slug=org.slug))
    context.set_user(
        UserContext(
            # Sentinel user id — audits record actor_type=api_key separately
            user_id=uuid4(),
            email=f"apikey:{key.prefix}",
            permission_keys=frozenset(key.scopes),
            api_key_id=key.id,
            api_key_scopes=frozenset(key.scopes),
        )
    )


async def meter_api_key_request(session: AsyncSession, organization_id: UUID) -> None:
    """Count one api_requests unit for a key-authenticated call.

    Uses `record` (never blocks): metering must not reject an API call mid-flight
    past its quota — `consume` on the api_requests metric is the blocking path
    and remains the domain app's explicit choice.
    """
    from synapse_saas.usage.service import UsageService

    try:
        await UsageService(session).record(organization_id, "api_requests", quantity=1)
    except Exception:
        logger.warning("api_key_metering_failed", organization_id=str(organization_id))
