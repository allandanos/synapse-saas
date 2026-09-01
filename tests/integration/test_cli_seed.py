"""CLI + cache integration: seed, plans sync, versioned cache."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
async def _fresh_engine(clean_db):
    from synapse_saas.core.db import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


class TestSeed:
    async def test_seed_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.core.db import get_session_factory
        from synapse_saas.seeds import seed_system
        from synapse_saas.subscriptions.catalog import load_catalog
        from synapse_saas.subscriptions.sync import sync_plans

        get_settings.cache_clear()
        factory = get_session_factory()
        async with factory() as session:
            first = await seed_system(session)
            await sync_plans(session, load_catalog("config/plans.yaml"))
            await session.commit()
        async with factory() as session:
            second = await seed_system(session)
            result = await sync_plans(session, load_catalog("config/plans.yaml"))
            await session.commit()

        # Second pass: everything already exists
        assert first == second
        assert result.plans_added == 0
        assert result.features_added == 0
        assert result.plans_updated == 0

    async def test_catalog_sync_updates_prices(self) -> None:
        """A YAML price change flows to the plan row but not to snapshots."""
        from sqlalchemy import select

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.subscriptions.catalog import load_catalog
        from synapse_saas.subscriptions.models import Plan
        from synapse_saas.subscriptions.sync import sync_plans

        factory = get_session_factory()
        catalog = load_catalog("config/plans.yaml")
        async with factory() as session:
            await sync_plans(session, catalog)
            await session.commit()

        # Simulate a price change in the catalog
        bumped = catalog.model_copy(deep=True)
        for plan in bumped.plans:
            if plan.key == "starter":
                plan.price_cents = 59900

        async with factory() as session:
            result = await sync_plans(session, bumped)
            await session.commit()
        assert result.plans_updated >= 1

        async with factory() as session:
            starter = (await session.execute(select(Plan).where(Plan.key == "starter"))).scalar_one()
            assert starter.price_cents == 59900


class TestVersionedCache:
    async def test_bump_invalidates(self) -> None:
        from synapse_saas.core.cache import VersionedCache

        cache = VersionedCache("test-ns", ttl=60)
        key = "cache-test"

        await cache.set(key, "v0-value")
        assert await cache.get(key) == "v0-value"

        await cache.bump(key)
        assert await cache.get(key) is None  # version moved; old body unreachable

        await cache.set(key, "v1-value")
        assert await cache.get(key) == "v1-value"

    async def test_ttl_dict_backend(self) -> None:
        from synapse_saas.core.cache import TTLDictBackend

        backend = TTLDictBackend()
        await backend.set("k", "1", ex=60)
        assert await backend.get("k") == "1"
        assert await backend.incr("k") == 2
        await backend.delete("k")
        assert await backend.get("k") is None


class TestHealthEndpoints:
    async def test_readyz_and_meta(self, client) -> None:
        ready = await client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] in {"ok", "error"}

        meta = await client.get("/v1/meta")
        assert meta.status_code == 200
        body = meta.json()
        assert body["framework"] == "synapse-saas"
        assert body["billing_provider"] == "manual"

    async def test_request_id_header(self, client) -> None:
        res = await client.get("/healthz", headers={"X-Request-Id": "req_test_123"})
        assert res.headers.get("X-Request-Id") == "req_test_123"

    async def test_problem_shape_on_domain_error(self, client) -> None:
        res = await client.get("/v1/auth/me")
        assert res.status_code == 401
        body = res.json()
        assert body["type"].startswith("https://synapse-saas.dev/problems/")
        assert body["status"] == 401


class TestAuthRouterRest:
    async def test_logout_and_refresh_cookie_flow(self, client) -> None:
        reg = await client.post(
            "/v1/auth/register",
            json={
                "email": "cookie@example.com",
                "password": "password12345",
                "display_name": "C",
            },
        )
        refresh_token = reg.json()["tokens"]["refresh_token"]

        # Refresh via cookie (no body)
        client.cookies.set("synapse_rt", refresh_token)
        refreshed = await client.post("/v1/auth/refresh", json={})
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"]

        logged_out = await client.post("/v1/auth/logout")
        assert logged_out.status_code == 204

        # The rotated cookie token is dead
        dead = await client.post("/v1/auth/refresh", json={})
        assert dead.status_code == 401

    async def test_forgot_password_is_opaque(self, client) -> None:
        res = await client.post("/v1/auth/forgot-password", json={"email": "ghost@example.com"})
        assert res.status_code == 202
        assert res.json() == {"ok": True}

    async def test_switch_org_requires_membership(self, client, org_and_tokens) -> None:
        import uuid

        res = await client.post(
            "/v1/auth/switch-org",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
            json={"organization_id": str(uuid.uuid4())},
        )
        assert res.status_code == 404
