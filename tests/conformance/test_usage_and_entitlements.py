"""Entitlements resolution and the metering contract (counters, gauges, idempotency)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_problem, grant_feature, uid


async def test_effective_entitlements_shape(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.get("/v1/entitlements", headers=tenant.headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plan_key"] == "free"
    assert isinstance(body["features"], list) and isinstance(body["limits"], dict)
    assert "api_requests" in body["limits"]


async def test_check_consume_summary(api: AsyncClient, tenant: Tenant) -> None:
    check = await api.get(
        "/v1/usage/check", headers=tenant.headers, params={"metric": "api_requests", "quantity": 1}
    )
    assert check.status_code == 200 and check.json()["within_limit"] is True

    consumed = await api.post(
        "/v1/usage/consume",
        headers=tenant.headers,
        json={"events": [{"metric": "api_requests", "quantity": 3}]},
    )
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["total"] >= 3

    summary = await api.get("/v1/usage/summary", headers=tenant.headers)
    assert summary.status_code == 200
    row = next(m for m in summary.json()["metrics"] if m["metric"] == "api_requests")
    assert row["used"] >= 3 and row["limit"] is not None


async def test_consume_rejects_multi_event_bodies(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post(
        "/v1/usage/consume",
        headers=tenant.headers,
        json={"events": [{"metric": "api_requests"}, {"metric": "api_requests"}]},
    )
    assert_problem(res, 422)


async def test_consume_batch_is_all_or_nothing(api: AsyncClient, tenant: Tenant) -> None:
    limit = (await api.get("/v1/entitlements", headers=tenant.headers)).json()["limits"]["api_requests"][
        "value"
    ]
    res = await api.post(
        "/v1/usage/consume-batch",
        headers=tenant.headers,
        json={
            "events": [
                {"metric": "api_requests", "quantity": 1},
                {"metric": "api_requests", "quantity": limit + 1},
            ]
        },
    )
    doc = assert_problem(res, 402, title="usage limit exceeded")
    assert doc["metric"] == "api_requests" and doc["limit"] == limit
    summary = await api.get("/v1/usage/summary", headers=tenant.headers)
    used = {m["metric"]: m["used"] for m in summary.json()["metrics"]}  # unmetered metrics are absent
    assert used.get("api_requests", 0) == 0


async def test_record_is_idempotent(api: AsyncClient, tenant: Tenant) -> None:
    key = f"evt-{uid()}"
    body = {"events": [{"metric": "api_requests", "quantity": 2, "idempotency_key": key}]}
    first = await api.post("/v1/usage/events", headers=tenant.headers, json=body)
    second = await api.post("/v1/usage/events", headers=tenant.headers, json=body)
    assert first.status_code == second.status_code == 201, second.text
    assert second.json()[0]["deduplicated"] is True
    summary = await api.get("/v1/usage/summary", headers=tenant.headers)
    assert next(m for m in summary.json()["metrics"] if m["metric"] == "api_requests")["used"] == 2


async def test_gauge_set_and_delta(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.post(
        "/v1/usage/gauge", headers=tenant.headers, json={"metric": "storage_bytes", "value": 1024}
    )
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 1024
    res = await api.post(
        "/v1/usage/gauge", headers=tenant.headers, json={"metric": "storage_bytes", "delta": -24}
    )
    assert res.json()["total"] == 1000
    counter_as_gauge = await api.post(
        "/v1/usage/gauge", headers=tenant.headers, json={"metric": "api_requests", "value": 1}
    )
    assert_problem(counter_as_gauge, 422)


async def test_feature_gate_problem_shape(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    gated = await api.get("/v1/agents", headers=tenant.headers)
    doc = assert_problem(gated, 403, title="feature not entitled")
    assert doc["feature"] == "agents" and isinstance(doc["available_in"], list)

    await grant_feature(api, platform, tenant["org_id"], "agents")
    assert (await api.get("/v1/agents", headers=tenant.headers)).status_code == 200


async def test_operator_entitlement_surface(
    api: AsyncClient, tenant: Tenant, platform: dict[str, str]
) -> None:
    self_grant = await api.post(
        f"/v1/admin/orgs/{tenant['org_id']}/entitlements/grants",
        headers=tenant.headers,
        json={"feature_key": "sso", "source": "beta"},
    )
    assert_problem(self_grant, 404)  # operator routes are invisible to tenants (ADR 0008)

    grant = await api.post(
        f"/v1/admin/orgs/{tenant['org_id']}/entitlements/grants",
        headers=platform,
        json={"feature_key": "sso", "source": "beta", "duration_days": 7},
    )
    assert grant.status_code in (200, 201), grant.text
    grant_id = grant.json()["id"]

    effective = await api.get(f"/v1/admin/orgs/{tenant['org_id']}/entitlements", headers=platform)
    assert effective.status_code == 200 and "sso" in effective.json()["features"]

    assert (
        await api.delete(
            f"/v1/admin/orgs/{tenant['org_id']}/entitlements/grants/{grant_id}", headers=platform
        )
    ).status_code == 204
    effective = await api.get("/v1/entitlements", headers=tenant.headers)
    assert "sso" not in effective.json()["features"]
