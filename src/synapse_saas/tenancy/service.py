"""Tenancy domain service.

Organization lifecycle + membership management. Every mutation writes audit +
outbox in the same transaction. Creating an org bootstraps the owner membership,
the owner system role, and a default-plan subscription so a new tenant is
immediately functional.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from synapse_saas.authorization.models import AuthorizationRole, MembershipRole
from synapse_saas.authorization.permissions import SYSTEM_ROLE_OWNER
from synapse_saas.core import events
from synapse_saas.core.errors import (
    InviteNotFoundError,
    MembershipLimitReachedError,
    NotAMemberError,
    OrganizationNotFoundError,
    SlugUnavailableError,
)
from synapse_saas.core.ids import is_valid_slug, slugify, unique_slug
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.identity.models import User
from synapse_saas.tenancy.models import Membership, Organization
from synapse_saas.tenancy.repository import MembershipRepository, OrganizationRepository

logger = get_logger(__name__)

INVITE_TOKEN_BYTES = 32


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orgs = OrganizationRepository(session)
        self.members = MembershipRepository(session)

    # ── Organizations ───────────────────────────────────────────────────────────

    async def create_organization(
        self,
        *,
        name: str,
        owner: User,
        slug: str | None = None,
    ) -> Organization:
        """Create org + owner membership + owner role + default subscription."""
        desired = slug or slugify(name)
        if desired and not is_valid_slug(desired):
            raise SlugUnavailableError(f"{desired!r} is reserved or invalid", extras={"slug": desired})
        final_slug = desired if desired and not await self.orgs.slug_exists(desired) else unique_slug(name)
        if not desired:
            final_slug = unique_slug(name)

        org = Organization(slug=final_slug, name=name, owner_user_id=owner.id)
        self.session.add(org)
        await self.session.flush()

        # Owner membership + role
        membership = Membership(
            organization_id=org.id,
            user_id=owner.id,
            status="active",
            joined_at=datetime.now(UTC),
        )
        self.session.add(membership)
        await self.session.flush()

        owner_role = (
            await self.session.execute(
                select(AuthorizationRole).where(
                    AuthorizationRole.key == SYSTEM_ROLE_OWNER,
                    AuthorizationRole.organization_id.is_(None),
                )
            )
        ).scalar_one()
        self.session.add(MembershipRole(membership_id=membership.id, role_id=owner_role.id))
        membership.permission_keys = (
            sorted(p.key for p in owner_role.permissions) if owner_role.permissions else []
        )

        self._audit(
            events.ORG_CREATED,
            organization_id=org.id,
            target_type="organization",
            target_id=org.id,
            diff={"name": name, "slug": final_slug},
        )
        append_outbox(
            self.session,
            event_type=events.ORG_CREATED,
            aggregate_type="organization",
            aggregate_id=org.id,
            organization_id=org.id,
            payload={"name": name, "slug": final_slug, "owner_user_id": str(owner.id)},
        )

        # Default-plan subscription so entitlements resolve immediately
        await self._bootstrap_subscription(org)

        logger.info("org_created", org_id=str(org.id), slug=final_slug)
        return org

    async def get_organization(self, org_id: UUID) -> Organization:
        org = await self.orgs.get(org_id)
        if org is None or org.deleted_at is not None:
            raise OrganizationNotFoundError("Organization not found")
        return org

    async def update_organization(
        self, org_id: UUID, *, name: str | None, settings: dict | None
    ) -> Organization:
        org = await self.get_organization(org_id)
        diff: dict = {}
        if name is not None and name != org.name:
            diff["name"] = {"from": org.name, "to": name}
            org.name = name
        if settings is not None:
            merged = {**org.settings, **settings}
            diff["settings"] = {"from": org.settings, "to": merged}
            org.settings = merged
        if diff:
            self._audit(events.ORG_UPDATED, organization_id=org_id, diff=diff)
        return org

    async def suspend_organization(self, org_id: UUID) -> Organization:
        org = await self.get_organization(org_id)
        org.status = "suspended"
        self._audit(events.ORG_SUSPENDED, organization_id=org_id)
        return org

    async def unsuspend_organization(self, org_id: UUID) -> Organization:
        org = await self.get_organization(org_id)
        org.status = "active"
        self._audit(events.ORG_UNSUSPENDED, organization_id=org_id)
        return org

    # ── Memberships ─────────────────────────────────────────────────────────────

    async def invite_member(
        self,
        *,
        organization_id: UUID,
        invited_email: str,
        invited_by_user_id: UUID,
        role_keys: list[str] | None = None,
        seat_limit: int | None = None,
    ) -> Membership:
        """Invite by email. Enforces the `users` gauge limit when provided."""
        active = await self.members.count_active_members(organization_id)
        pending = await self._count_pending_invites(organization_id)
        if seat_limit is not None and active + pending + 1 > seat_limit:
            raise MembershipLimitReachedError(
                "Seat limit reached for the current plan",
                extras={
                    "metric": "users",
                    "limit": seat_limit,
                    "used": active + pending,
                    "upgrade_url": "/dashboard/billing",
                },
            )

        membership = Membership(
            organization_id=organization_id,
            invited_email=invited_email,
            status="invited",
        )
        self.session.add(membership)
        await self.session.flush()

        for key in role_keys or ["member"]:
            await self._attach_role(membership, key)

        # roles relationship isn't populated on new objects; load it for the response
        await self.session.refresh(membership, attribute_names=["roles", "user"])
        token = self._issue_invite_token(membership)
        self._audit(
            events.MEMBER_INVITED,
            organization_id=organization_id,
            target_type="membership",
            target_id=membership.id,
            diff={"email": invited_email, "roles": role_keys or ["member"]},
        )
        append_outbox(
            self.session,
            event_type=events.MEMBER_INVITED,
            aggregate_type="membership",
            aggregate_id=membership.id,
            organization_id=organization_id,
            payload={"email": invited_email, "token_hash": _hash(token)},
        )
        return membership

    async def accept_invite_by_email(self, org_id: UUID, email: str) -> Membership:
        membership = await self.members.find_pending_invite(org_id, email)
        if membership is None:
            raise InviteNotFoundError("No pending invite for this email")
        # If a user with this email exists, link them (registration-before-accept)
        user = (await self.session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        return await self._accept(membership, user)

    async def accept_invite_by_token(self, token: str, user: User) -> Membership:
        membership = (
            await self.session.execute(
                select(Membership).where(
                    Membership.invite_token_hash == _hash(token),
                    Membership.status == "invited",
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            raise InviteNotFoundError("Invite not found or already used")
        membership.invite_token_hash = None  # single-use
        return await self._accept(membership, user)

    async def update_membership(
        self,
        membership_id: UUID,
        *,
        role_keys: list[str] | None = None,
        status: str | None = None,
    ) -> Membership:
        membership = await self._get_membership(membership_id)
        diff: dict = {}

        if role_keys is not None:
            await self._replace_roles(membership, role_keys)
            diff["roles"] = role_keys
        if status is not None and status != membership.status:
            diff["status"] = {"from": membership.status, "to": status}
            membership.status = status

        membership = await self._reload(membership.id)
        if diff:
            self._audit(
                events.MEMBER_UPDATED,
                organization_id=membership.organization_id,
                target_type="membership",
                target_id=membership.id,
                diff=diff,
            )
        return membership

    async def remove_member(self, membership_id: UUID) -> None:
        membership = await self._get_membership(membership_id)
        org = await self.get_organization(membership.organization_id)
        if membership.user_id == org.owner_user_id:
            raise NotAMemberError("The owner cannot be removed; transfer ownership first")

        self._audit(
            events.MEMBER_REMOVED,
            organization_id=membership.organization_id,
            target_type="membership",
            target_id=membership.id,
            diff={"email": membership.invited_email or str(membership.user_id)},
        )
        await self.session.delete(membership)

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _accept(self, membership: Membership, user: User | None) -> Membership:
        """Convert an invite into an active membership."""
        if user is not None:
            membership.user_id = user.id
            membership.invited_email = user.email
        membership.status = "active"
        membership.joined_at = datetime.now(UTC)
        await self.session.flush()

        self._audit(
            events.MEMBER_JOINED,
            organization_id=membership.organization_id,
            target_type="membership",
            target_id=membership.id,
            diff={"email": membership.invited_email},
        )
        append_outbox(
            self.session,
            event_type=events.MEMBER_JOINED,
            aggregate_type="membership",
            aggregate_id=membership.id,
            organization_id=membership.organization_id,
            payload={"email": membership.invited_email},
        )
        return membership

    async def _bootstrap_subscription(self, org: Organization) -> None:
        """Create the default-plan subscription for a brand-new org."""
        from synapse_saas.core.config import get_settings
        from synapse_saas.subscriptions.models import Plan
        from synapse_saas.subscriptions.service import SubscriptionService

        settings = get_settings()
        plan = (
            await self.session.execute(select(Plan).where(Plan.key == settings.default_plan_key))
        ).scalar_one_or_none()
        if plan is None:
            logger.warning("default_plan_missing", key=settings.default_plan_key)
            return

        now = datetime.now(UTC)
        from datetime import timedelta

        subscription_service = SubscriptionService(self.session)
        await subscription_service.create_subscription(
            organization_id=org.id,
            plan=plan,
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )

    async def _attach_role(self, membership: Membership, role_key: str) -> None:
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
            from synapse_saas.core.errors import RoleNotFoundError

            raise RoleNotFoundError(f"Role {role_key!r} not found")
        self.session.add(MembershipRole(membership_id=membership.id, role_id=role.id))
        membership.permission_keys = sorted({*membership.permission_keys, *(p.key for p in role.permissions)})

    async def _replace_roles(self, membership: Membership, role_keys: list[str]) -> None:
        from sqlalchemy import delete

        await self.session.execute(
            delete(MembershipRole).where(MembershipRole.membership_id == membership.id)
        )
        membership.permission_keys = []
        for key in role_keys:
            await self._attach_role(membership, key)
        await self._invalidate_perms(membership)

    async def _get_membership(self, membership_id: UUID) -> Membership:
        membership = (
            await self.session.execute(
                select(Membership)
                .options(selectinload(Membership.roles))
                .where(Membership.id == membership_id)
            )
        ).scalar_one_or_none()
        if membership is None:
            raise NotAMemberError("Membership not found")
        return membership

    async def _reload(self, membership_id: UUID) -> Membership:
        """Evict then re-fetch: role rows were deleted/inserted via bulk DML, so
        the identity-map copy would serve stale relationship state."""
        await self.session.flush()
        self.session.expire_all()
        return await self._get_membership(membership_id)

    async def _count_pending_invites(self, org_id: UUID) -> int:
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == org_id, Membership.status == "invited")
        )
        return int(result.scalar_one())

    def _issue_invite_token(self, membership: Membership) -> str:
        token = secrets.token_urlsafe(INVITE_TOKEN_BYTES)
        membership.invite_token_hash = _hash(token)
        return token

    async def _invalidate_perms(self, membership: Membership) -> None:
        """Drop cached permissions for this member so the next request recomputes."""
        if membership.user_id is None:
            return
        from synapse_saas.authorization.service import AuthorizationService

        await AuthorizationService(self.session).invalidate_user_perms(
            membership.user_id, membership.organization_id
        )

    def _audit(
        self,
        event_type: str,
        *,
        organization_id: UUID | None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        diff: dict | None = None,
    ) -> None:
        from synapse_saas.audit.service import AuditService

        AuditService(self.session).log(
            event_type,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            diff=diff,
        )


def _hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()
