"""Conformance harness (P6 / WS-K).

Two modes, same tests:

* **in-process** (default): the framework's own ASGI app on the scratch database,
  via the public pytest plugin. Needs Postgres, hence the `pg` marker is added.
* **external**: `SYNAPSE_CONFORMANCE_API_URL=https://host` runs the identical
  journeys over the network against any implementation of the v1 contract —
  the Python reference, or a port (ADR 0012). Platform-operator journeys need
  `SYNAPSE_CONFORMANCE_ADMIN_EMAIL` / `SYNAPSE_CONFORMANCE_ADMIN_PASSWORD`, else
  they skip.

Every journey creates its own user/org with a random suffix so the suite can be
re-run against a live server without cleanup.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response

EXTERNAL_URL = os.environ.get("SYNAPSE_CONFORMANCE_API_URL", "").rstrip("/")
PASSWORD = "conformance-password-12345"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/conformance" not in str(item.fspath).replace(os.sep, "/"):
            continue
        item.add_marker(pytest.mark.conformance)
        if not EXTERNAL_URL:
            item.add_marker(pytest.mark.pg)


if EXTERNAL_URL:

    @pytest_asyncio.fixture
    async def api() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(base_url=EXTERNAL_URL, timeout=30.0) as http:
            yield http

    @pytest_asyncio.fixture
    async def platform(api: AsyncClient) -> dict[str, str]:
        email = os.environ.get("SYNAPSE_CONFORMANCE_ADMIN_EMAIL")
        password = os.environ.get("SYNAPSE_CONFORMANCE_ADMIN_PASSWORD")
        if not email or not password:
            pytest.skip("platform-operator journeys need SYNAPSE_CONFORMANCE_ADMIN_EMAIL/PASSWORD")
        res = await api.post("/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        return {"Authorization": f"Bearer {res.json()['tokens']['access_token']}"}

else:

    @pytest_asyncio.fixture
    async def api(client: AsyncClient) -> AsyncClient:
        return client

    @pytest_asyncio.fixture
    async def platform(api: AsyncClient) -> dict[str, str]:
        from synapse_saas.testing.fixtures import platform_admin_headers

        return await platform_admin_headers(api)


def uid() -> str:
    return uuid.uuid4().hex[:8]


class Tenant(dict[str, Any]):
    """A fresh owner + org. `headers` carries bearer + X-Org-Id."""

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self['access_token']}", "X-Org-Id": self["org_id"]}

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self['access_token']}"}


async def make_tenant(api: AsyncClient, *, label: str = "owner") -> Tenant:
    tag = uid()
    email = f"{label}-{tag}@conformance.example.com"
    reg = await api.post(
        "/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": label.title()},
    )
    assert reg.status_code == 201, reg.text
    tokens = reg.json()["tokens"]
    org = await api.post(
        "/v1/orgs",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"name": f"Org {tag}", "slug": f"org-{tag}"},
    )
    assert org.status_code == 201, org.text
    return Tenant(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        org_id=org.json()["id"],
        user_id=reg.json()["user"]["id"],
        email=email,
        password=PASSWORD,
        slug=f"org-{tag}",
    )


@pytest_asyncio.fixture
async def tenant(api: AsyncClient) -> Tenant:
    return await make_tenant(api)


async def grant_feature(api: AsyncClient, platform: dict[str, str], org_id: str, feature: str) -> None:
    res = await api.post(
        f"/v1/admin/orgs/{org_id}/entitlements/grants",
        headers=platform,
        json={"feature_key": feature, "source": "beta"},
    )
    assert res.status_code in (200, 201), res.text


def assert_problem(res: Response, status: int, *, title: str | None = None) -> dict[str, Any]:
    """Every error is an RFC 7807 problem document with the framework's extensions."""
    assert res.status_code == status, f"{res.status_code} != {status}: {res.text}"
    assert res.headers["content-type"].startswith("application/json"), res.headers.get("content-type")
    doc = res.json()
    assert set(doc) >= {"type", "title", "status"}, doc
    assert doc["status"] == status, doc
    assert doc["type"].startswith("https://synapse-saas.dev/problems/"), doc["type"]
    if status != 422:  # validation problems come from the framework's request parser
        assert doc.get("request_id"), "problem documents carry the server request id"
    if title is not None:
        assert doc["title"] == title, doc
    return doc


def assert_envelope(res: Response) -> dict[str, Any]:
    """Envelope lists (`orgs`, `members`): `{data, meta: {total, limit, offset}}`."""
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["data"], list) and {"total", "limit", "offset"} <= set(body["meta"]), body
    return body


def assert_page(res: Response) -> list[Any]:
    """List routes: plain JSON array body + X-Total-Count."""
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body, list), body
    assert "x-total-count" in res.headers, "list routes expose X-Total-Count"
    assert int(res.headers["x-total-count"]) >= len(body)
    return body
