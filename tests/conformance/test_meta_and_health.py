"""Discovery + liveness surface."""

from __future__ import annotations

from httpx import AsyncClient


async def test_meta_describes_the_deployment(api: AsyncClient) -> None:
    res = await api.get("/v1/meta")
    assert res.status_code == 200, res.text
    meta = res.json()
    assert {"version", "billing_provider", "identity_provider", "tenant_isolation"} <= set(meta), meta
    assert meta["tenant_isolation"] in {"app", "app_and_rls"}


async def test_health_probes(api: AsyncClient) -> None:
    live = await api.get("/healthz")
    assert live.status_code == 200 and live.json()["status"] == "ok"
    ready = await api.get("/readyz")
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ok"
    assert "database" in ready.json()["checks"]
