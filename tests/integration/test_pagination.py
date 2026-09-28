"""Every list route paginates the same way (P4 / WS-F F4): `?limit=&offset=`,
a plain-list body (unchanged for existing clients) and `X-Total-Count`."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.integration.conftest import platform_admin_headers

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


TENANT_LIST_ROUTES = (
    "/v1/api-keys",
    "/v1/webhooks/endpoints",
    "/v1/webhooks/deliveries",
    "/v1/billing/invoices",
    "/v1/files",
    "/v1/plans",
)


class TestEveryListRoute:
    @pytest.mark.parametrize("path", TENANT_LIST_ROUTES)
    async def test_total_count_header_and_limit(self, client: AsyncClient, org_and_tokens, path: str) -> None:
        res = await client.get(path, headers=org_headers(org_and_tokens), params={"limit": 1, "offset": 0})
        assert res.status_code == 200, (path, res.text)
        assert isinstance(res.json(), list)
        assert "X-Total-Count" in res.headers, path
        assert len(res.json()) <= 1
        assert int(res.headers["X-Total-Count"]) >= len(res.json())

    @pytest.mark.parametrize("path", TENANT_LIST_ROUTES)
    async def test_limit_is_bounded(self, client: AsyncClient, org_and_tokens, path: str) -> None:
        res = await client.get(path, headers=org_headers(org_and_tokens), params={"limit": 101})
        assert res.status_code == 422, path

    async def test_agents_route_paginates_too(self, client: AsyncClient, org_and_tokens) -> None:
        from tests.integration.conftest import grant_as_platform

        await grant_as_platform(client, org_and_tokens["org_id"], {"feature_key": "agents", "source": "beta"})
        res = await client.get("/v1/agents", headers=org_headers(org_and_tokens), params={"limit": 5})
        assert res.status_code == 200, res.text
        assert res.headers["X-Total-Count"] == "0"

    async def test_platform_lists_paginate(self, client: AsyncClient) -> None:
        admin = await platform_admin_headers(client)
        for key in ("pg-a", "pg-b", "pg-c"):
            created = await client.post("/v1/feature-flags", headers=admin, json={"key": key, "name": key})
            assert created.status_code == 201, created.text
        page1 = await client.get("/v1/feature-flags", headers=admin, params={"limit": 2, "offset": 0})
        page2 = await client.get("/v1/feature-flags", headers=admin, params={"limit": 2, "offset": 2})
        assert page1.headers["X-Total-Count"] == "3" and len(page1.json()) == 2
        assert len(page2.json()) == 1
        assert {f["key"] for f in page1.json() + page2.json()} == {"pg-a", "pg-b", "pg-c"}


class TestPagesWalkTheWholeSet:
    async def test_api_keys_pages_do_not_overlap(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        for i in range(5):
            assert (
                await client.post("/v1/api-keys", headers=headers, json={"name": f"k{i}"})
            ).status_code == 201
        seen: list[str] = []
        offset = 0
        while True:
            res = await client.get("/v1/api-keys", headers=headers, params={"limit": 2, "offset": offset})
            ids = [k["id"] for k in res.json()]
            if not ids:
                break
            seen.extend(ids)
            offset += 2
        assert len(seen) == 5 and len(set(seen)) == 5
        assert res.headers["X-Total-Count"] == "5"

    async def test_files_cap_is_gone(self, client: AsyncClient, org_and_tokens) -> None:
        """The old route hard-capped at 200 rows with no way past; now it pages."""
        res = await client.get(
            "/v1/files", headers=org_headers(org_and_tokens), params={"limit": 100, "offset": 300}
        )
        assert res.status_code == 200 and res.json() == []
        assert res.headers["X-Total-Count"] == "0"

    async def test_cors_exposes_the_total(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get(
            "/v1/plans", headers={**org_headers(org_and_tokens), "Origin": "http://localhost:3000"}
        )
        exposed = res.headers.get("access-control-expose-headers", "")
        assert "X-Total-Count" in exposed
