"""Agents registry (ADR 0007): feature-gated CRUD + enable/disable."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, assert_page, assert_problem, grant_feature, uid


async def test_agent_lifecycle(api: AsyncClient, tenant: Tenant, platform: dict[str, str]) -> None:
    await grant_feature(api, platform, tenant["org_id"], "agents")
    slug = f"bot-{uid()}"
    created = await api.post(
        "/v1/agents", headers=tenant.headers, json={"slug": slug, "name": "Bot", "config": {"model": "x"}}
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    assert created.json()["status"] in {"enabled", "active"}

    assert_problem(
        await api.post(
            "/v1/agents", headers=tenant.headers, json={"slug": slug, "name": "Bot", "config": {}}
        ),
        409,
    )

    got = await api.get(f"/v1/agents/{agent_id}", headers=tenant.headers)
    assert got.status_code == 200 and got.json()["slug"] == slug

    patched = await api.patch(f"/v1/agents/{agent_id}", headers=tenant.headers, json={"name": "Bot 2"})
    assert patched.status_code == 200 and patched.json()["name"] == "Bot 2"

    disabled = await api.post(f"/v1/agents/{agent_id}/disable", headers=tenant.headers)
    assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
    enabled = await api.post(f"/v1/agents/{agent_id}/enable", headers=tenant.headers)
    assert enabled.status_code == 200 and enabled.json()["status"] != "disabled"

    listed = assert_page(await api.get("/v1/agents", headers=tenant.headers))
    assert [a["id"] for a in listed] == [agent_id]

    assert (await api.delete(f"/v1/agents/{agent_id}", headers=tenant.headers)).status_code == 204
    assert_problem(await api.get(f"/v1/agents/{agent_id}", headers=tenant.headers), 404)
