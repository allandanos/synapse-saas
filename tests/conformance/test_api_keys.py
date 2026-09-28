"""API keys: create-once secret, bounded scopes, key auth without X-Org-Id, revoke."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem


async def test_key_lifecycle(api: AsyncClient, tenant: Tenant) -> None:
    created = await api.post(
        "/v1/api-keys", headers=tenant.headers, json={"name": "ci", "scopes": ["usage:read"]}
    )
    assert created.status_code == 201, created.text
    secret = created.json()["key"]
    assert secret.startswith("sk_")
    key_id = created.json()["id"]

    listed = assert_page(await api.get("/v1/api-keys", headers=tenant.headers))
    assert [k["id"] for k in listed] == [key_id]
    assert "key" not in listed[0] or listed[0]["key"] != secret, "the secret is shown exactly once"

    as_key = {"Authorization": f"Bearer {secret}"}
    ok = await api.post(
        "/v1/usage/consume", headers=as_key, json={"events": [{"metric": "api_requests", "quantity": 1}]}
    )
    assert ok.status_code == 200, ok.text
    out_of_scope = await api.get("/v1/orgs/current/members", headers=as_key)
    assert_problem(out_of_scope, 403)

    assert (await api.delete(f"/v1/api-keys/{key_id}", headers=tenant.headers)).status_code == 204
    assert_problem(await api.get("/v1/usage/summary", headers=as_key), 401)


async def test_scopes_are_bounded_by_the_creator(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post("/v1/api-keys", headers=tenant.headers, json={"name": "x", "scopes": ["nope:nope"]})
    assert res.status_code in (403, 422), res.text
    assert_problem(res, res.status_code)
