"""Development seeds: demo org + one user per system role for click-throughs.

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

DEV_PASSWORD = "password123"

# One demo user per system role. The owner also carries is_platform_admin so
# the admin console is reachable in dev. Domain is example.com (RFC 2606):
# EmailStr REJECTS the .test TLD as special-use, which would make demo users
# impossible to log in. Emails are load-bearing — extend, don't rename.
DEV_ROLE_USERS: tuple[tuple[str, str], ...] = (
    ("owner@acme.example.com", "owner"),
    ("admin@acme.example.com", "admin"),
    ("billing@acme.example.com", "billing"),
    ("developer@acme.example.com", "developer"),
    ("member@acme.example.com", "member"),
)

DEV_OWNER_EMAIL = "owner@acme.example.com"
DEV_MEMBER_EMAIL = "member@acme.example.com"


def _assert_loginable_emails() -> None:
    """Every demo email must pass the API's own EmailStr validation.

    The seeder writes users straight through the ORM; without this guard a
    reserved-domain edit would sail past validation and produce demo users
    that cannot log in (exactly the @acme.test bug this replaced).
    """
    from pydantic import EmailStr, TypeAdapter

    adapter = TypeAdapter(EmailStr)
    for email, _role in DEV_ROLE_USERS:
        adapter.validate_python(email)  # raises on reserved/invalid domains


async def seed_dev(session: AsyncSession) -> None:
    from sqlalchemy import select

    _assert_loginable_emails()

    existing = (await session.execute(select(User).where(User.email == DEV_OWNER_EMAIL))).scalar_one_or_none()
    if existing is not None:
        logger.info("dev_seed_skipped", reason="already seeded")
        return

    org_service = OrganizationService(session)

    # Owner first: creates the org (owner role attaches at creation)
    owner = User(
        email=DEV_OWNER_EMAIL,
        password_hash=hash_password(DEV_PASSWORD),
        display_name="Acme Owner",
        is_platform_admin=True,
    )
    session.add(owner)
    await session.flush()

    org = await org_service.create_organization(
        name="Acme Corporation",
        owner=owner,
        slug="acme",
    )

    # One user per remaining system role, invited + auto-accepted
    for email, role_key in DEV_ROLE_USERS:
        if email == DEV_OWNER_EMAIL:
            continue
        user = User(
            email=email,
            password_hash=hash_password(DEV_PASSWORD),
            display_name=f"Acme {role_key.capitalize()}",
        )
        session.add(user)
        await session.flush()

        await org_service.invite_member(
            organization_id=org.id,
            invited_email=email,
            invited_by_user_id=owner.id,
            role_keys=[role_key],
        )
        # Auto-accept the dev invite so the user can log in and see the org
        await org_service.accept_invite_by_email(org.id, email)

    logger.info(
        "dev_seeded",
        org=org.slug,
        roles=[role for _, role in DEV_ROLE_USERS],
        note="demo credentials are in the CLI output",
    )
