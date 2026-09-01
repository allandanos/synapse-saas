"""Organization + membership endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status

from synapse_saas.core import context
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import PlatformAdminDep, TenantDep
from synapse_saas.tenancy.schemas import (
    MemberInvite,
    MembershipPage,
    MembershipRead,
    MemberUpdate,
    OrganizationCreate,
    OrganizationPage,
    OrganizationRead,
    OrganizationUpdate,
)
from synapse_saas.tenancy.service import OrganizationService

router = APIRouter(tags=["orgs"])


def _to_membership_read(m) -> MembershipRead:  # type: ignore[no-untyped-def]
    read = MembershipRead.model_validate(m)
    if m.user is not None:
        read.email = str(m.user.email)
        read.display_name = m.user.display_name
    read.role_keys = sorted(r.key for r in m.roles)
    return read


# ── Organizations ──────────────────────────────────────────────────────────────


@router.get("/orgs", response_model=OrganizationPage)
async def list_my_orgs(user: CurrentUser, session: SessionDep) -> OrganizationPage:
    from synapse_saas.tenancy.repository import MembershipRepository

    memberships = await MembershipRepository(session).for_user(user.id)
    orgs = [OrganizationRead.model_validate(m.organization) for m in memberships]
    return OrganizationPage.build(orgs, total=len(orgs), limit=100, offset=0)


@router.post("/orgs", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreate, user: CurrentUser, session: SessionDep
) -> OrganizationRead:
    service = OrganizationService(session)
    org = await service.create_organization(name=body.name, owner=user, slug=body.slug)
    return OrganizationRead.model_validate(org)


@router.get("/orgs/current", response_model=OrganizationRead)
async def get_current_org(tenant: TenantDep, session: SessionDep) -> OrganizationRead:
    service = OrganizationService(session)
    org = await service.get_organization(tenant.organization_id)
    return OrganizationRead.model_validate(org)


@router.patch("/orgs/current", response_model=OrganizationRead)
async def update_current_org(
    body: OrganizationUpdate,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> OrganizationRead:
    from synapse_saas.authorization.dependencies import require_permission

    await require_permission("org:update", user, session, tenant)
    service = OrganizationService(session)
    org = await service.update_organization(
        tenant.organization_id,
        name=body.name,
        settings=body.settings,  # type: ignore[arg-type]
    )
    return OrganizationRead.model_validate(org)


# ── Members ────────────────────────────────────────────────────────────────────


@router.get("/orgs/current/members", response_model=MembershipPage)
async def list_members(
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> MembershipPage:
    from synapse_saas.authorization.dependencies import require_permission

    await require_permission("member:read", user, session, tenant)
    service = OrganizationService(session)
    members = await service.members.for_organization(tenant.organization_id, limit=limit, offset=offset)
    total = await service.members.count_active_members(
        tenant.organization_id
    ) + await service._count_pending_invites(tenant.organization_id)
    return MembershipPage.build(
        [_to_membership_read(m) for m in members], total=total, limit=limit, offset=offset
    )


@router.post(
    "/orgs/current/members/invite", response_model=MembershipRead, status_code=status.HTTP_201_CREATED
)
async def invite_member(
    body: MemberInvite,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> MembershipRead:
    from synapse_saas.authorization.dependencies import require_permission
    from synapse_saas.entitlements.service import EntitlementService

    await require_permission("member:invite", user, session, tenant)
    context.set_tenant(tenant)

    # Seat (gauge) limit enforced inside the same transaction as the insert
    entitlements = await EntitlementService(session).effective_for_org(tenant.organization_id)
    seat_limit = entitlements.limit_value("users")

    service = OrganizationService(session)
    membership = await service.invite_member(
        organization_id=tenant.organization_id,
        invited_email=str(body.email),
        invited_by_user_id=user.id,
        role_keys=body.role_keys,
        seat_limit=seat_limit,
    )
    return _to_membership_read(membership)


@router.patch("/memberships/{membership_id}", response_model=MembershipRead)
async def update_membership(
    membership_id: UUID,
    body: MemberUpdate,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> MembershipRead:
    from synapse_saas.authorization.dependencies import require_permission
    from synapse_saas.core.errors import NotAMemberError
    from synapse_saas.tenancy.models import Membership

    await require_permission("member:update", user, session, tenant)
    context.set_tenant(tenant)
    membership = await session.get(Membership, membership_id)
    if membership is None or membership.organization_id != tenant.organization_id:
        raise NotAMemberError("Membership not found")  # 404 cross-tenant

    service = OrganizationService(session)
    updated = await service.update_membership(membership_id, role_keys=body.role_keys, status=body.status)
    return _to_membership_read(updated)


@router.delete("/memberships/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: UUID,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> None:
    from synapse_saas.authorization.dependencies import require_permission
    from synapse_saas.core.errors import NotAMemberError
    from synapse_saas.tenancy.models import Membership

    await require_permission("member:remove", user, session, tenant)
    context.set_tenant(tenant)
    membership = await session.get(Membership, membership_id)
    if membership is None or membership.organization_id != tenant.organization_id:
        raise NotAMemberError("Membership not found")
    await OrganizationService(session).remove_member(membership_id)


# ── Platform admin ─────────────────────────────────────────────────────────────


@router.post("/orgs/{org_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def suspend_org(org_id: UUID, platform: PlatformAdminDep, session: SessionDep) -> None:
    await OrganizationService(session).suspend_organization(org_id)


@router.delete("/orgs/{org_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
async def unsuspend_org(org_id: UUID, platform: PlatformAdminDep, session: SessionDep) -> None:
    await OrganizationService(session).unsuspend_organization(org_id)
