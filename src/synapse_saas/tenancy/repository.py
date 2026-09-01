"""Tenancy repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from synapse_saas.core.repository import Repository, TenantRepository
from synapse_saas.tenancy.models import Membership, Organization


class OrganizationRepository(Repository[Organization]):
    model = Organization

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(
            select(Organization).where(Organization.slug == slug, Organization.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None


class MembershipRepository(TenantRepository[Membership]):
    model = Membership

    async def for_organization(self, org_id: UUID, *, limit: int = 100, offset: int = 0) -> list[Membership]:
        result = await self.session.execute(
            select(Membership)
            .options(selectinload(Membership.user), selectinload(Membership.roles))
            .where(Membership.organization_id == org_id)
            .order_by(Membership.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def for_user(self, user_id: UUID) -> list[Membership]:
        result = await self.session.execute(
            select(Membership)
            .options(selectinload(Membership.organization), selectinload(Membership.roles))
            .where(Membership.user_id == user_id, Membership.status == "active")
        )
        return list(result.scalars().all())

    async def get_active(self, org_id: UUID, user_id: UUID) -> Membership | None:
        result = await self.session.execute(
            select(Membership)
            .options(selectinload(Membership.roles))
            .where(
                Membership.organization_id == org_id,
                Membership.user_id == user_id,
                Membership.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def find_pending_invite(self, org_id: UUID, email: str) -> Membership | None:
        result = await self.session.execute(
            select(Membership).where(
                Membership.organization_id == org_id,
                Membership.invited_email == email,
                Membership.status == "invited",
            )
        )
        return result.scalar_one_or_none()

    async def count_active_members(self, org_id: UUID) -> int:
        return await self.count(organization_id=org_id, status="active")
