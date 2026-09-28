"""Defects the conformance suite surfaced while freezing contract v1 (P6 / WS-K).

Each test pins the corrected behaviour so the reference implementation and the
ports (ADR 0012) agree on it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from synapse_saas.testing.fixtures import org_headers, platform_admin_headers

pytestmark = pytest.mark.pg


class TestValidationProblems:
    async def test_request_parsing_failures_are_problem_documents(self, client: AsyncClient) -> None:
        res = await client.post("/v1/auth/register", json={"email": "nope", "password": "x"})
        assert res.status_code == 422
        doc = res.json()
        assert doc["type"].endswith("/validation_failed") and doc["title"] == "validation failed"
        assert doc["status"] == 422 and doc["request_id"] and doc["instance"] == "/v1/auth/register"
        assert doc["detail"].startswith("Invalid request: email")
        locs = {tuple(e["loc"]) for e in doc["errors"]}
        assert ("body", "email") in locs and ("body", "display_name") in locs

    async def test_query_validation_too(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/plans", headers=org_headers(org_and_tokens), params={"limit": 0})
        assert res.status_code == 422 and res.json()["title"] == "validation failed"
        assert res.json()["errors"][0]["loc"] == ["query", "limit"]


class TestSuspensionAppliesToEveryPrincipal:
    async def test_jwt_members_are_locked_out_while_suspended(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        admin = await platform_admin_headers(client)
        org_id = org_and_tokens["org_id"]
        assert (await client.post(f"/v1/orgs/{org_id}/suspend", headers=admin)).status_code == 204

        res = await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))
        assert res.status_code == 403, res.text
        assert res.json()["title"] == "organization suspended"
        assert res.json()["organization_id"] == org_id and res.json()["organization_status"] == "suspended"
        assert res.json()["status"] == 403  # extras never shadow the RFC 7807 members

        # Writes too — the whole tenant surface is closed, not just the profile
        blocked = await client.post(
            "/v1/api-keys", headers=org_headers(org_and_tokens), json={"name": "while-suspended"}
        )
        assert blocked.status_code == 403

        assert (await client.delete(f"/v1/orgs/{org_id}/suspend", headers=admin)).status_code == 204
        assert (await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))).status_code == 200

    async def test_non_members_still_get_404_not_403(self, client: AsyncClient, org_and_tokens) -> None:
        """Suspension must not become an existence oracle."""
        admin = await platform_admin_headers(client)
        org_id = org_and_tokens["org_id"]
        assert (await client.post(f"/v1/orgs/{org_id}/suspend", headers=admin)).status_code == 204
        reg = await client.post(
            "/v1/auth/register",
            json={"email": "stranger@example.com", "password": "password12345", "display_name": "S"},
        )
        stranger = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}", "X-Org-Id": org_id}
        assert (await client.get("/v1/orgs/current", headers=stranger)).status_code == 404


class TestRoleUpdateReturnsTheNewSet:
    async def test_patch_permissions_replaces_and_reflects(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        created = await client.post(
            "/v1/roles",
            headers=headers,
            json={"key": "auditor", "name": "Auditor", "permissions": ["audit:read", "org:read"]},
        )
        assert created.status_code == 201, created.text
        patched = await client.patch(
            f"/v1/roles/{created.json()['id']}", headers=headers, json={"permissions": ["org:read"]}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["permissions"] == ["org:read"]
        listed = await client.get("/v1/roles", headers=headers)
        assert next(r for r in listed.json() if r["key"] == "auditor")["permissions"] == ["org:read"]


class TestPresignDownloadOnLocalDisk:
    async def test_answers_409_presign_unsupported(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        up = await client.post("/v1/files", headers=headers, files={"file": ("a.txt", b"x", "text/plain")})
        assert up.status_code == 201, up.text
        res = await client.post(f"/v1/files/{up.json()['id']}/presign", headers=headers)
        assert res.status_code == 409 and res.json()["title"] == "presign unsupported"
