"""Audit log: every mutating journey leaves attributable rows, paginated + filterable."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conformance.conftest import Tenant, uid


async def test_audit_page_and_filters(api: AsyncClient, tenant: Tenant) -> None:
    created = await api.post("/v1/api-keys", headers=tenant.headers, json={"name": f"k-{uid()}"})
    assert created.status_code == 201

    page = await api.get("/v1/audit", headers=tenant.headers, params={"limit": 5})
    assert page.status_code == 200, page.text
    body = page.json()
    assert {"data", "next_cursor"} <= set(body), body
    assert 1 <= len(body["data"]) <= 5
    row = body["data"][0]
    assert {"event_type", "actor_user_id", "created_at"} <= set(row), row

    filtered = await api.get("/v1/audit", headers=tenant.headers, params={"event_type": row["event_type"]})
    assert all(r["event_type"] == row["event_type"] for r in filtered.json()["data"])

    by_actor = await api.get("/v1/audit", headers=tenant.headers, params={"actor_user_id": tenant["user_id"]})
    assert len(by_actor.json()["data"]) >= 1
