"""Migration 0019 round-trip against real rows: the system `member` role gains
member:read and every membership holding it is recomputed (custom roles kept)."""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.integration.conftest import org_headers, owner_session_factory

pytestmark = pytest.mark.pg

PREVIOUS = "0018_user_preferences"
EMAIL = "auditor@migration.example"


async def _alembic(direction: str, target: str) -> None:
    """Alembic is sync — run it in a thread (the `migrated_db` fixture's pattern)."""

    def _run() -> None:
        from alembic import command

        from synapse_saas.cli import alembic_config

        getattr(command, direction)(alembic_config(), target)

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, _run)


async def _stored_keys(email: str) -> list[str]:
    async with owner_session_factory()() as session:
        row = await session.execute(
            text(
                "SELECT m.permission_keys FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE u.email = :email"
            ),
            {"email": email},
        )
        return list(row.scalar_one())


async def _member_role_grants_member_read() -> bool:
    async with owner_session_factory()() as session:
        row = await session.execute(
            text(
                "SELECT count(*) FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id JOIN permissions p ON p.id = rp.permission_id "
                "WHERE r.key = 'member' AND r.is_system AND r.organization_id IS NULL "
                "AND p.key = 'member:read'"
            )
        )
        return bool(row.scalar_one())


async def _me_keys(client: AsyncClient, token: str) -> list[str]:
    res = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    return list(res.json()["orgs"][0]["permission_keys"])


async def test_member_read_downgrade_and_upgrade_recompute_member_holders(
    client: AsyncClient, org_and_tokens
) -> None:
    owner = org_headers(org_and_tokens)
    role = await client.post(
        "/v1/roles", headers=owner, json={"key": "auditor", "name": "Auditor", "permissions": ["audit:read"]}
    )
    assert role.status_code == 201, role.text
    reg = await client.post(
        "/v1/auth/register", json={"email": EMAIL, "password": "password12345", "display_name": "A"}
    )
    assert reg.status_code == 201, reg.text
    inv = await client.post(
        "/v1/orgs/current/members/invite",
        headers=owner,
        json={"email": EMAIL, "role_keys": ["member", "auditor"]},
    )
    assert inv.status_code == 201, inv.text
    from synapse_saas.tenancy.service import OrganizationService

    async with owner_session_factory()() as session:
        await OrganizationService(session).accept_invite_by_email(uuid.UUID(org_and_tokens["org_id"]), EMAIL)
        await session.commit()

    owner_before = await _stored_keys("owner@example.com")
    assert await _stored_keys(EMAIL) == ["audit:read", "member:read", "org:read", "project:read"]

    try:
        await _alembic("downgrade", PREVIOUS)
        assert not await _member_role_grants_member_read()
        assert await _stored_keys(EMAIL) == ["audit:read", "org:read", "project:read"]
        assert await _stored_keys("owner@example.com") == owner_before
    finally:
        await _alembic("upgrade", "head")  # never leave the shared test DB below head

    assert await _member_role_grants_member_read()
    assert await _stored_keys(EMAIL) == ["audit:read", "member:read", "org:read", "project:read"]
    assert await _stored_keys("owner@example.com") == owner_before
    assert await _me_keys(client, reg.json()["tokens"]["access_token"]) == [
        "audit:read",
        "member:read",
        "org:read",
        "project:read",
    ]
