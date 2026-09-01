"""Development seeds: demo org + users for local click-throughs.

NEVER runs in production — guarded by env check in the CLI.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.billing import models as _billing_models  # noqa: F401 — FK resolution order
from synapse_saas.core.logging import get_logger
from synapse_saas.core.security import hash_password
from synapse_saas.identity.models import User
from synapse_saas.tenancy.service import OrganizationService

logger = get_logger(__name__)

DEV_OWNER_EMAIL = "owner@acme.test"
DEV_MEMBER_EMAIL = "member@acme.test"
DEV_PASSWORD = "password123"


async def seed_dev(session: AsyncSession) -> None:
    from sqlalchemy import select

    existing = (await session.execute(select(User).where(User.email == DEV_OWNER_EMAIL))).scalar_one_or_none()
    if existing is not None:
        logger.info("dev_seed_skipped", reason="already seeded")
        return

    owner = User(
        email=DEV_OWNER_EMAIL,
        password_hash=hash_password(DEV_PASSWORD),
        display_name="Acme Owner",
        is_platform_admin=True,
    )
    member = User(
        email=DEV_MEMBER_EMAIL,
        password_hash=hash_password(DEV_PASSWORD),
        display_name="Acme Member",
    )
    session.add_all([owner, member])
    await session.flush()

    org_service = OrganizationService(session)
    org = await org_service.create_organization(
        name="Acme Corporation",
        owner=owner,
        slug="acme",
    )
    await org_service.invite_member(
        organization_id=org.id,
        invited_email=DEV_MEMBER_EMAIL,
        invited_by_user_id=owner.id,
        role_keys=["member"],
    )
    # Auto-accept the dev invite so the member can log in and see the org
    await org_service.accept_invite_by_email(org.id, DEV_MEMBER_EMAIL)

    logger.info(
        "dev_seeded",
        org=org.slug,
        owner=DEV_OWNER_EMAIL,
        member=DEV_MEMBER_EMAIL,
        note="demo credentials are in the CLI output",
    )
