"""Outbound webhooks: endpoint secret shown once, paginated deliveries, retry semantics."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem, uid


async def test_endpoint_lifecycle(api: AsyncClient, tenant: Tenant) -> None:
    created = await api.post(
        "/v1/webhooks/endpoints",
        headers=tenant.headers,
        json={"url": f"https://hooks.example.com/{uid()}", "events": ["member.invited"], "description": "c"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["secret"].startswith("whsec_")
    endpoint_id = created.json()["id"]

    listed = assert_page(await api.get("/v1/webhooks/endpoints", headers=tenant.headers))
    assert listed[0]["id"] == endpoint_id and "secret" not in listed[0]

    audit = await api.get(
        "/v1/audit", headers=tenant.headers, params={"event_type": "webhook.endpoint_created"}
    )
    assert audit.status_code == 200 and [r["target_id"] for r in audit.json()["data"]] == [endpoint_id]
    assert "secret" not in audit.text

    deliveries = assert_page(
        await api.get("/v1/webhooks/deliveries", headers=tenant.headers, params={"endpoint_id": endpoint_id})
    )
    assert deliveries == []

    assert_problem(
        await api.post(f"/v1/webhooks/deliveries/{endpoint_id}/retry", headers=tenant.headers), 404
    )
    assert (
        await api.delete(f"/v1/webhooks/endpoints/{endpoint_id}", headers=tenant.headers)
    ).status_code == 204
    assert_problem(await api.delete(f"/v1/webhooks/endpoints/{endpoint_id}", headers=tenant.headers), 404)
    deleted = await api.get(
        "/v1/audit", headers=tenant.headers, params={"event_type": "webhook.endpoint_deleted"}
    )
    assert [r["target_id"] for r in deleted.json()["data"]] == [endpoint_id]


async def test_endpoint_url_must_be_https_or_valid(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post(
        "/v1/webhooks/endpoints", headers=tenant.headers, json={"url": "not a url", "events": []}
    )
    assert_problem(res, 422)
