"""Every error body is a problem document — including the ones the framework itself raises."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_problem


async def test_unknown_route_is_a_problem(api: AsyncClient) -> None:
    doc = assert_problem(await api.get("/v1/definitely-not-a-route"), 404, title="not found")
    assert doc["instance"] == "/v1/definitely-not-a-route"


async def test_wrong_method_is_a_problem(api: AsyncClient, tenant: Tenant) -> None:
    assert_problem(await api.put("/v1/orgs", headers=tenant.bearer, json={}), 405, title="method not allowed")


async def test_request_id_is_echoed(api: AsyncClient) -> None:
    res = await api.get("/v1/meta", headers={"X-Request-Id": "req_conformance_1"})
    assert res.status_code == 200
    assert res.headers.get("x-request-id") == "req_conformance_1"
