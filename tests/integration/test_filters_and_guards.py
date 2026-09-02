"""Audit filters, role listing, dependency guards."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


class TestAuditFilters:
    async def test_filter_by_event_type(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/orgs/current/members/invite", headers=headers, json={"email": "f@example.com"})

        all_entries = (await client.get("/v1/audit", headers=headers)).json()["data"]
        assert all_entries

        filtered = (
            await client.get("/v1/audit", headers=headers, params={"event_type": "member.invited"})
        ).json()["data"]
        assert filtered
        assert all(e["event_type"] == "member.invited" for e in filtered)

        none = (await client.get("/v1/audit", headers=headers, params={"event_type": "nope.nope"})).json()[
            "data"
        ]
        assert none == []

    async def test_filter_by_actor(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        res = (
            await client.get(
                "/v1/audit",
                headers=headers,
                params={"actor_user_id": str(uuid.uuid4())},
            )
        ).json()["data"]
        assert res == []

    async def test_pagination_params(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        res = await client.get("/v1/audit", headers=headers, params={"limit": 1, "offset": 0})
        assert res.status_code == 200
        assert len(res.json()["data"]) <= 1


class TestRolesEndpoint:
    async def test_system_roles_listed_with_permissions(self, client: AsyncClient, org_and_tokens) -> None:
        roles = (await client.get("/v1/roles", headers=org_headers(org_and_tokens))).json()
        keys = {r["key"] for r in roles}
        assert {"owner", "admin", "member", "billing", "developer"} <= keys

        owner = next(r for r in roles if r["key"] == "owner")
        assert "org:delete" in owner["permissions"]
        assert len(owner["permissions"]) >= 17

    async def test_permissions_catalog_endpoint(self, client: AsyncClient, org_and_tokens) -> None:
        perms = (
            await client.get(
                "/v1/permissions", headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"}
            )
        ).json()
        assert len(perms) >= 17
        assert all("key" in p and "resource" in p and "action" in p for p in perms)


class TestTenantResolutionVariants:
    async def test_org_slug_header(self, client: AsyncClient, org_and_tokens) -> None:
        """X-Org-Slug resolves the same tenant as X-Org-Id."""
        from sqlalchemy import select

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.tenancy.models import Organization

        factory = get_session_factory()
        async with factory() as session:
            org = (
                await session.execute(
                    select(Organization).where(Organization.id == uuid.UUID(org_and_tokens["org_id"]))
                )
            ).scalar_one()

        res = await client.get(
            "/v1/entitlements",
            headers={
                "Authorization": f"Bearer {org_and_tokens['access_token']}",
                "X-Org-Slug": org.slug,
            },
        )
        assert res.status_code == 200

    async def test_invalid_org_id_header(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get(
            "/v1/entitlements",
            headers={
                "Authorization": f"Bearer {org_and_tokens['access_token']}",
                "X-Org-Id": "not-a-uuid",
            },
        )
        assert res.status_code == 404

    async def test_bearer_without_org_still_resolves_via_jwt_claim(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        """switch-org bakes the org into the token; X-Org-Id becomes optional."""
        headers = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        switched = await client.post(
            "/v1/auth/switch-org",
            headers=headers,
            json={"organization_id": org_and_tokens["org_id"]},
        )
        assert switched.status_code == 200
        scoped_token = switched.json()["access_token"]

        res = await client.get("/v1/entitlements", headers={"Authorization": f"Bearer {scoped_token}"})
        assert res.status_code == 200
        assert res.json()["plan_key"] == "free"
