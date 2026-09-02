"""Tenant resolution dependency.

Order: X-Org-Id / X-Org-Slug header → JWT `org` claim → subdomain.
Then a membership check (Redis-cached). Failure is 404 — never 403 — so the
API doesn't leak which organizations exist.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core.cache import VersionedCache
from synapse_saas.core.context import TenantContext, current_tenant, set_tenant
from synapse_saas.core.db import get_session
from synapse_saas.core.errors import AuthenticationError, TenantNotResolvedError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.security import decode_access_token
from synapse_saas.identity.dependencies import CurrentUser
from synapse_saas.tenancy.models import Organization
from synapse_saas.tenancy.repository import MembershipRepository, OrganizationRepository

logger = get_logger(__name__)

_membership_cache = VersionedCache("member", ttl=60)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _resolve_org_reference(request: Request, user: CurrentUser) -> UUID | str | None:
    org_id = request.headers.get("X-Org-Id")
    if org_id:
        try:
            return UUID(org_id)
        except ValueError:
            raise TenantNotResolvedError("Invalid X-Org-Id header") from None

    org_slug = request.headers.get("X-Org-Slug")
    if org_slug:
        return org_slug

    # Subdomain: acme.localhost / acme.app.example.com (skip www, api, app)
    host = request.headers.get("host", "").split(":")[0].lower()
    if "." in host and host.split(".")[0] not in {"www", "api", "app"}:
        return host.split(".")[0]

    # JWT org claim (set at token mint when an org is active)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_access_token(auth.removeprefix("Bearer "))
            org = payload.get("org")
            if org:
                return UUID(str(org))
        except AuthenticationError:
            logger.debug("jwt_org_claim_unreadable")  # resolution falls through
    return None


async def resolve_tenant(request: Request, user: CurrentUser, session: SessionDep) -> TenantContext:
    # API-key auth pins the tenant during get_principal; membership checks don't
    # apply (the key IS its org's credential). Reuse the bound context directly.
    existing = current_tenant()
    if existing is not None and not existing.is_platform:
        return existing

    reference = await _resolve_org_reference(request, user)
    if reference is None:
        raise TenantNotResolvedError("No organization context for this request")

    orgs = OrganizationRepository(session)
    members = MembershipRepository(session)

    org: Organization | None = None
    if isinstance(reference, UUID):
        org = await orgs.get(reference)
    else:
        org = await orgs.get_by_slug(str(reference))

    if org is None or org.deleted_at is not None:
        raise TenantNotResolvedError("Organization not found")

    membership = await members.get_active(org.id, user.id)
    if membership is None and not user.is_platform_admin:
        raise TenantNotResolvedError("Organization not found")  # identical response: no existence leak

    context = TenantContext(organization_id=org.id, slug=org.slug)
    # Bind for the rest of the request: tenant-scoped repositories, audit, logs.
    set_tenant(context)
    return context


TenantDep = Annotated[TenantContext, Depends(resolve_tenant)]


async def require_platform_admin(user: CurrentUser) -> TenantContext:
    """Platform-scope dependency for admin surfaces (no tenant filtering)."""
    if not user.is_platform_admin:
        raise TenantNotResolvedError("Not found")
    return TenantContext(organization_id=UUID(int=0), slug="platform", is_platform=True)


PlatformAdminDep = Annotated[TenantContext, Depends(require_platform_admin)]
