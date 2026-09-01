"""TenantRepository enforcement — the security primitive, directly tested.

All work happens inside one test (one event loop): the cached engine is bound
to whichever loop first touched it, so per-test loops cannot share it.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
async def _fresh_engine(clean_db):
    """Each test gets its own event loop; the cached engine must not outlive one.

    dispose_engine() drops the module-level engine so the next get_engine()
    binds to this test's loop.
    """
    from synapse_saas.core.db import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


async def test_membership_rows_are_tenant_scoped(clean_db) -> None:
    from sqlalchemy import select

    from synapse_saas.core.context import TenantContext, TenantScope
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.identity.models import User
    from synapse_saas.tenancy.models import Membership, Organization
    from synapse_saas.tenancy.repository import MembershipRepository

    factory = get_session_factory()
    async with factory() as session:
        owner = User(email=f"repo-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name="R")
        session.add(owner)
        await session.flush()
        org_a = Organization(slug=f"a-{uuid.uuid4().hex[:6]}", name="A", owner_user_id=owner.id)
        org_b = Organization(slug=f"b-{uuid.uuid4().hex[:6]}", name="B", owner_user_id=owner.id)
        session.add_all([org_a, org_b])
        await session.flush()
        session.add(Membership(organization_id=org_a.id, invited_email="ma@example.com", status="invited"))
        session.add(Membership(organization_id=org_b.id, invited_email="mb@example.com", status="invited"))
        await session.commit()

        b_row = (
            await session.execute(select(Membership).where(Membership.organization_id == org_b.id))
        ).scalar_one()

        # In A's scope: only A's row is visible; B's row id resolves to None
        with TenantScope(TenantContext(organization_id=org_a.id, slug=org_a.slug)):
            repo = MembershipRepository(session)
            rows = await repo.list()
            assert len(rows) == 1
            assert rows[0].organization_id == org_a.id
            assert await repo.get(b_row.id) is None
            assert await repo.count() == 1


async def test_cross_tenant_add_raises(clean_db) -> None:
    """Attaching an object stamped with another org raises TenantViolationError."""
    from synapse_saas.core.context import TenantContext, TenantScope
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.core.errors import TenantViolationError
    from synapse_saas.identity.models import User
    from synapse_saas.tenancy.models import Membership, Organization
    from synapse_saas.tenancy.repository import MembershipRepository

    factory = get_session_factory()
    async with factory() as session:
        owner = User(email=f"x-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name="X")
        session.add(owner)
        await session.flush()
        org_a = Organization(slug=f"a-{uuid.uuid4().hex[:6]}", name="A", owner_user_id=owner.id)
        org_b = Organization(slug=f"b-{uuid.uuid4().hex[:6]}", name="B", owner_user_id=owner.id)
        session.add_all([org_a, org_b])
        await session.commit()

        with TenantScope(TenantContext(organization_id=org_a.id, slug=org_a.slug)):
            repo = MembershipRepository(session)
            foreign = Membership(organization_id=org_b.id, invited_email="f@example.com", status="invited")
            with pytest.raises(TenantViolationError):
                await repo.add(foreign)


async def test_add_stamps_tenant(clean_db) -> None:
    """add() injects the active tenant when the object is unstamped."""
    from synapse_saas.core.context import TenantContext, TenantScope
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.identity.models import User
    from synapse_saas.tenancy.models import Membership, Organization
    from synapse_saas.tenancy.repository import MembershipRepository

    factory = get_session_factory()
    async with factory() as session:
        owner = User(email=f"s-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name="S")
        session.add(owner)
        await session.flush()
        org = Organization(slug=f"o-{uuid.uuid4().hex[:6]}", name="O", owner_user_id=owner.id)
        session.add(org)
        await session.commit()

        with TenantScope(TenantContext(organization_id=org.id, slug=org.slug)):
            repo = MembershipRepository(session)
            membership = Membership(invited_email="stamped@example.com", status="invited")
            await repo.add(membership)
            assert membership.organization_id == org.id


async def test_platform_scope_requires_explicit_tenant(clean_db) -> None:
    """Platform contexts must pass tenant_id explicitly — no ambient guessing."""
    from synapse_saas.core.context import TenantContext, TenantScope
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.core.errors import TenantViolationError
    from synapse_saas.tenancy.repository import MembershipRepository

    factory = get_session_factory()
    async with factory() as session:
        with TenantScope(TenantContext(organization_id=uuid.uuid4(), slug="platform", is_platform=True)):
            repo = MembershipRepository(session)
            with pytest.raises(TenantViolationError):
                repo.tenant_id  # noqa: B018 — property access must refuse


async def test_no_context_requires_explicit_tenant(clean_db) -> None:
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.core.errors import TenantViolationError
    from synapse_saas.tenancy.repository import MembershipRepository

    factory = get_session_factory()
    async with factory() as session:
        repo = MembershipRepository(session)
        with pytest.raises(TenantViolationError):
            repo.tenant_id  # noqa: B018
