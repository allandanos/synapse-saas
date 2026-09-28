"""Feature flags: tenant check + platform-admin CRUD and overrides."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem, uid


async def test_unknown_flag_is_off(api: AsyncClient, tenant: Tenant) -> None:
    res = await api.get(f"/v1/feature-flags/check/nope-{uid()}", headers=tenant.headers)
    assert res.status_code == 200 and res.json()["enabled"] is False


async def test_admin_crud_and_overrides(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    key = f"flag-{uid()}"
    assert_problem(
        await api.post("/v1/feature-flags", headers=tenant.headers, json={"key": key, "name": key}), 404
    )

    created = await api.post(
        "/v1/feature-flags", headers=platform, json={"key": key, "name": key, "enabled": False}
    )
    assert created.status_code == 201, created.text
    assert_problem(await api.post("/v1/feature-flags", headers=platform, json={"key": key, "name": key}), 409)

    listed = assert_page(await api.get("/v1/feature-flags", headers=platform, params={"limit": 100}))
    assert key in {f["key"] for f in listed}

    off = await api.get(f"/v1/feature-flags/check/{key}", headers=tenant.headers)
    assert off.json()["enabled"] is False

    override = await api.post(
        f"/v1/feature-flags/{key}/overrides",
        headers=platform,
        json={"organization_id": tenant["org_id"], "enabled": True, "note": "conformance"},
    )
    assert override.status_code == 201, override.text
    on = await api.get(f"/v1/feature-flags/check/{key}", headers=tenant.headers)
    assert on.json()["enabled"] is True

    overrides = assert_page(await api.get(f"/v1/feature-flags/{key}/overrides", headers=platform))
    assert [o["id"] for o in overrides] == [override.json()["id"]]

    assert (
        await api.delete(f"/v1/feature-flags/overrides/{override.json()['id']}", headers=platform)
    ).status_code == 204
    updated = await api.patch(f"/v1/feature-flags/{key}", headers=platform, json={"enabled": True})
    assert updated.status_code == 200 and updated.json()["enabled"] is True
    assert (await api.get(f"/v1/feature-flags/check/{key}", headers=tenant.headers)).json()["enabled"] is True
