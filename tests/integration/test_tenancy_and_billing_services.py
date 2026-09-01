"""Remaining service flows: org management, members, invoices, portal."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


class TestOrgManagement:
    async def test_update_org_profile(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.patch(
            "/v1/orgs/current",
            headers=org_headers(org_and_tokens),
            json={"name": "Renamed Org"},
        )
        assert res.status_code == 200
        assert res.json()["name"] == "Renamed Org"

    async def test_get_current_org(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    async def test_list_my_orgs(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get(
            "/v1/orgs", headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        )
        assert res.status_code == 200
        assert res.json()["meta"]["total"] == 1

    async def test_second_org_for_same_user(self, client: AsyncClient, org_and_tokens) -> None:
        """One user, many orgs — the multi-tenant membership model."""
        token = org_and_tokens["access_token"]
        res = await client.post(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Second Org", "slug": "second-org"},
        )
        assert res.status_code == 201

        orgs = (await client.get("/v1/orgs", headers={"Authorization": f"Bearer {token}"})).json()
        assert orgs["meta"]["total"] == 2

    async def test_reserved_slug_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
            json={"name": "Admin Corp", "slug": "admin"},
        )
        assert res.status_code == 409

    async def test_duplicate_slug_gets_suffix(self, client: AsyncClient, org_and_tokens) -> None:
        """Slug conflicts resolve to a unique suffix, not a failure."""
        res = await client.post(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
            json={"name": "Test Org", "slug": "test-org"},
        )
        assert res.status_code == 201
        assert res.json()["slug"].startswith("test-org")
        assert res.json()["slug"] != "test-org"


class TestMembershipManagement:
    async def test_list_members(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/orgs/current/members", headers=org_headers(org_and_tokens))
        assert res.status_code == 200
        members = res.json()["data"]
        assert len(members) >= 1  # the owner
        owner = members[0]
        assert "owner" in owner["role_keys"]

    async def test_update_membership_roles(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        invite = await client.post(
            "/v1/orgs/current/members/invite",
            headers=headers,
            json={"email": "promote@example.com", "role_keys": ["member"]},
        )
        membership_id = invite.json()["id"]

        res = await client.patch(
            f"/v1/memberships/{membership_id}",
            headers=headers,
            json={"role_keys": ["admin"]},
        )
        assert res.status_code == 200, res.text
        assert "admin" in res.json()["role_keys"]

    async def test_suspend_membership(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        invite = await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "susp@example.com"}
        )
        membership_id = invite.json()["id"]

        res = await client.patch(
            f"/v1/memberships/{membership_id}", headers=headers, json={"status": "suspended"}
        )
        assert res.status_code == 200
        assert res.json()["status"] == "suspended"

    async def test_remove_member(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        invite = await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "gone@example.com"}
        )
        membership_id = invite.json()["id"]

        res = await client.delete(f"/v1/memberships/{membership_id}", headers=headers)
        assert res.status_code == 204


class TestUsageCheckEndpoint:
    async def test_pre_flight_check(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post(
            "/v1/usage/events",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 42}]},
        )
        res = await client.get("/v1/usage/check", headers=headers, params={"metric": "api_requests"})
        assert res.status_code == 200
        body = res.json()
        assert body["used"] == 42
        assert body["limit"] == 10_000
        assert body["within_limit"] is True

    async def test_batch_events(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/usage/events",
            headers=org_headers(org_and_tokens),
            json={
                "events": [
                    {"metric": "api_requests", "quantity": 5},
                    {"metric": "api_requests", "quantity": 7, "idempotency_key": "batch-1"},
                ]
            },
        )
        assert res.status_code == 201
        assert len(res.json()) == 2

    async def test_batch_limit_enforced(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/usage/events",
            headers=org_headers(org_and_tokens),
            json={"events": [{"metric": "api_requests"}] * 101},
        )
        assert res.status_code == 422


class TestEntitlementGrantValidation:
    async def test_invalid_source_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/entitlements/grants",
            headers=org_headers(org_and_tokens),
            json={"feature_key": "sso", "source": "magic"},
        )
        assert res.status_code == 422

    async def test_limit_addon_grant_changes_cap(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={
                "feature_key": "limit:api_requests",
                "source": "addon",
                "limit_value": 50,
            },
        )
        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert ent["limits"]["api_requests"]["value"] == 50
