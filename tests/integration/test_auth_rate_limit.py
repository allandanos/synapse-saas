"""Auth rate limiting middleware — end-to-end through the app."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
def _tight_limits(monkeypatch: pytest.MonkeyPatch):
    """Small limits so tests don't need many requests; reset the limiter after."""
    from synapse_saas.core import rate_limit as rl_module
    from synapse_saas.core.config import get_settings

    monkeypatch.setenv("SYNAPSE_AUTH_RATE_LIMIT_PER_IP", "50")
    monkeypatch.setenv("SYNAPSE_AUTH_RATE_LIMIT_PER_IDENTITY", "3")
    monkeypatch.setenv("SYNAPSE_AUTH_RATE_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    rl_module.reset_rate_limiter()
    yield
    get_settings.cache_clear()
    rl_module.reset_rate_limiter()


class TestIdentityLimit:
    async def test_attempts_over_cap_are_429(self, client: AsyncClient) -> None:
        """Wrong-password attempts against one account trip at the identity cap.

        Register also counts against the identity bucket (creating the account
        is an auth action on that identity), so 1 register + 2 logins reach 3.
        """
        await client.post(
            "/v1/auth/register",
            json={
                "email": "stuffed@example.com",
                "password": "password12345",
                "display_name": "S",
            },
        )
        for _ in range(2):
            res = await client.post(
                "/v1/auth/login",
                json={"email": "stuffed@example.com", "password": "wrong-password-1"},
            )
            assert res.status_code == 401  # normal rejection while under the cap

        blocked = await client.post(
            "/v1/auth/login",
            json={"email": "stuffed@example.com", "password": "wrong-password-1"},
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["type"].endswith("/rate_limited")
        assert body["retry_after_seconds"] >= 1
        assert blocked.headers["Retry-After"] == str(body["retry_after_seconds"])

    async def test_other_identity_unaffected(self, client: AsyncClient) -> None:
        """Blocking one account doesn't block a different one from the same IP."""
        await client.post(
            "/v1/auth/register",
            json={
                "email": "victim@example.com",
                "password": "password12345",
                "display_name": "V",
            },
        )
        for _ in range(3):  # register(1) + logins(2) = cap of 3
            await client.post(
                "/v1/auth/login",
                json={"email": "victim@example.com", "password": "wrong-password-x"},
            )
        blocked = await client.post(
            "/v1/auth/login",
            json={"email": "victim@example.com", "password": "wrong-password-x"},
        )
        assert blocked.status_code == 429

        other = await client.post(
            "/v1/auth/login",
            json={"email": "someone-else@example.com", "password": "wrong-password-x"},
        )
        assert other.status_code == 401  # not 429 — different identity bucket


class TestNonAuthRoutes:
    async def test_health_and_orgs_unlimited(self, client: AsyncClient, org_and_tokens) -> None:
        for _ in range(10):
            res = await client.get("/healthz")
            assert res.status_code == 200
        res = await client.get(
            "/v1/orgs", headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        )
        assert res.status_code == 200


class TestMiddlewareBehavior:
    async def test_body_still_reaches_handler(self, client: AsyncClient) -> None:
        """The middleware peeks at the body; the handler must still parse it."""
        res = await client.post(
            "/v1/auth/register",
            json={
                "email": "peek@example.com",
                "password": "password12345",
                "display_name": "P",
            },
        )
        assert res.status_code == 201
        assert res.json()["user"]["email"] == "peek@example.com"

    async def test_malformed_body_does_not_crash_limiter(self, client: AsyncClient) -> None:
        res = await client.post(
            "/v1/auth/login",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        # Falls through to normal 422 parsing; the limiter never raises
        assert res.status_code == 422
