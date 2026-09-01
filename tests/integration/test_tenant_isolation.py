"""Tenant isolation — the framework's flagship security suite.

Two orgs, two users. Every cross-tenant request must be a clean 404 with an
identical body to a nonexistent-org request (no existence leak).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


@pytest.fixture
async def two_worlds(client: AsyncClient) -> dict[str, dict[str, str]]:
    """Org A owned by user A; org B owned by user B."""
    worlds = {}
    for label, email in (("a", "a@isol.example"), ("b", "b@isol.example")):
        reg = await client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": "password12345",
                "display_name": f"User {label.upper()}",
            },
        )
        assert reg.status_code == 201
        tokens = reg.json()["tokens"]
        org = await client.post(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={"name": f"Org {label.upper()}"},
        )
        assert org.status_code == 201
        worlds[label] = {
            "access_token": tokens["access_token"],
            "org_id": org.json()["id"],
        }
    return worlds


PHANTOM = "00000000-0000-0000-0000-000000000000"

CROSS_TENANT_PATHS = [
    "/v1/entitlements",
    "/v1/audit",
    "/v1/billing/invoices",
    "/v1/orgs/current/members",
    "/v1/webhooks/endpoints",
]


class TestCrossTenantDenied:
    @pytest.mark.parametrize("path", CROSS_TENANT_PATHS)
    async def test_cross_tenant_is_404(self, client: AsyncClient, two_worlds, path: str) -> None:
        """B's token against A's org → 404 on every org-scoped endpoint."""
        headers = {
            "Authorization": f"Bearer {two_worlds['b']['access_token']}",
            "X-Org-Id": two_worlds["a"]["org_id"],
        }
        res = await client.get(path, headers=headers)
        assert res.status_code == 404, f"{path} leaked: {res.status_code}"

    async def test_own_org_is_200(self, client: AsyncClient, two_worlds) -> None:
        headers = {
            "Authorization": f"Bearer {two_worlds['b']['access_token']}",
            "X-Org-Id": two_worlds["b"]["org_id"],
        }
        res = await client.get("/v1/entitlements", headers=headers)
        assert res.status_code == 200

    async def test_phantom_org_identical_response(self, client: AsyncClient, two_worlds) -> None:
        """404 for a real foreign org and a phantom org must be byte-identical."""
        token = two_worlds["b"]["access_token"]
        foreign = await client.get(
            "/v1/entitlements",
            headers={"Authorization": f"Bearer {token}", "X-Org-Id": two_worlds["a"]["org_id"]},
        )
        phantom = await client.get(
            "/v1/entitlements",
            headers={"Authorization": f"Bearer {token}", "X-Org-Id": PHANTOM},
        )
        assert foreign.status_code == phantom.status_code == 404
        assert foreign.json() == phantom.json()

    async def test_no_org_context_rejected(self, client: AsyncClient, two_worlds) -> None:
        res = await client.get(
            "/v1/entitlements",
            headers={"Authorization": f"Bearer {two_worlds['a']['access_token']}"},
        )
        assert res.status_code == 404

    async def test_cross_tenant_membership_write_blocked(self, client: AsyncClient, two_worlds) -> None:
        """A tries to modify B's membership row by id → 404 before any write."""
        invite = await client.post(
            "/v1/orgs/current/members/invite",
            headers={
                "Authorization": f"Bearer {two_worlds['b']['access_token']}",
                "X-Org-Id": two_worlds["b"]["org_id"],
            },
            json={"email": "someone@x.example"},
        )
        assert invite.status_code == 201
        membership_id = invite.json()["id"]

        res = await client.patch(
            f"/v1/memberships/{membership_id}",
            headers={
                "Authorization": f"Bearer {two_worlds['a']['access_token']}",
                "X-Org-Id": two_worlds["a"]["org_id"],
            },
            json={"status": "suspended"},
        )
        assert res.status_code == 404

    async def test_rival_cannot_suspend_other_org(self, client: AsyncClient, two_worlds) -> None:
        """Platform-admin endpoints deny non-admins even with a valid token."""
        res = await client.post(
            f"/v1/orgs/{two_worlds['a']['org_id']}/suspend",
            headers={"Authorization": f"Bearer {two_worlds['b']['access_token']}"},
        )
        assert res.status_code == 404
