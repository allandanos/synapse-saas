"""Auth rate-limit middleware: 429 on limit, fail-open on infrastructure error, refresh covered."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from synapse_saas.core import rate_limit as rl_module
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import RateLimitedError
from synapse_saas.identity.rate_limit import AUTH_ROUTES, AuthRateLimitMiddleware


class _Boom:
    async def check(self, *a, **k):  # type: ignore[no-untyped-def]
        raise ConnectionError("redis down")


class _Limited:
    async def check(self, *a, **k):  # type: ignore[no-untyped-def]
        raise RateLimitedError("slow down", extras={"retry_after_seconds": 7})


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthRateLimitMiddleware)

    @app.post("/v1/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "login"}

    @app.post("/v1/auth/refresh")
    async def refresh() -> dict[str, str]:
        return {"ok": "refresh"}

    @app.get("/v1/plans")
    async def plans() -> dict[str, str]:
        return {"ok": "plans"}

    return app


@pytest.fixture(autouse=True)
def _settings():  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    rl_module.reset_rate_limiter()
    yield
    get_settings.cache_clear()
    rl_module.reset_rate_limiter()


def test_refresh_is_an_auth_route() -> None:
    assert "/v1/auth/refresh" in AUTH_ROUTES
    assert AUTH_ROUTES["/v1/auth/refresh"] is None  # IP bucket only; no identity in the body


async def test_infrastructure_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rl_module, "get_rate_limiter", _Boom)
    import synapse_saas.identity.rate_limit as mw

    monkeypatch.setattr(mw, "get_rate_limiter", _Boom)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        res = await c.post("/v1/auth/login", json={"email": "a@example.com"})
    assert res.status_code == 200, res.text  # a Redis blip must not 429 every login


async def test_limit_hit_is_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    import synapse_saas.identity.rate_limit as mw

    monkeypatch.setattr(mw, "get_rate_limiter", _Limited)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        res = await c.post("/v1/auth/refresh", json={})
    assert res.status_code == 429
    assert res.headers["Retry-After"] == "7"
    assert res.json()["retry_after_seconds"] == 7


async def test_non_auth_routes_bypass_the_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    import synapse_saas.identity.rate_limit as mw

    monkeypatch.setattr(mw, "get_rate_limiter", _Limited)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        res = await c.get("/v1/plans")
    assert res.status_code == 200
