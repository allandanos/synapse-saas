"""Plans and the subscription state machine."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem


async def test_plans_are_a_paginated_catalog(api: AsyncClient, tenant: Tenant) -> None:
    plans = assert_page(await api.get("/v1/plans", headers=tenant.headers))
    keys = {p["key"] for p in plans}
    assert "free" in keys
    assert all({"key", "name", "price_cents", "features", "limits"} <= set(p) for p in plans), plans[0]
    assert (await api.get("/v1/plans", headers=tenant.headers, params={"limit": 101})).status_code == 422


async def test_new_org_is_on_free(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.get("/v1/subscription", headers=tenant.headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {"subscription", "entitlements", "usage"} <= set(body), body
    assert body["subscription"]["plan"]["key"] == "free"
    assert body["subscription"]["status"] in {"active", "trialing"}
    assert body["entitlements"]["plan_key"] == "free"


async def test_trial_cancel_resume(api: AsyncClient, tenant: Tenant) -> None:
    plans = (await api.get("/v1/plans", headers=tenant.headers)).json()
    paid = next(p["key"] for p in plans if p["price_cents"] > 0)

    trial = await api.post("/v1/subscription/trial", headers=tenant.headers, json={"plan_key": paid})
    assert trial.status_code == 201, trial.text
    assert trial.json()["status"] == "trialing" and trial.json()["plan"]["key"] == paid

    again = await api.post("/v1/subscription/trial", headers=tenant.headers, json={"plan_key": paid})
    assert_problem(again, 409)

    cancelled = await api.post(
        "/v1/subscription/cancel", headers=tenant.headers, json={"at_period_end": True}
    )
    assert cancelled.status_code == 200 and cancelled.json()["cancel_at_period_end"] is True

    resumed = await api.post("/v1/subscription/resume", headers=tenant.headers)
    assert resumed.status_code == 200 and resumed.json()["cancel_at_period_end"] is False


async def test_change_to_unknown_plan_is_404(api: AsyncClient, tenant: Tenant) -> None:
    assert_problem(
        await api.post("/v1/subscription/change", headers=tenant.headers, json={"plan_key": "nope"}), 404
    )
