"""Auth flow: register → login → refresh rotation → reuse detection → logout."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


class TestRegistration:
    async def test_register_returns_tokens(self, client: AsyncClient) -> None:
        res = await client.post(
            "/v1/auth/register",
            json={
                "email": "new@auth.example",
                "password": "password12345",
                "display_name": "New",
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]
        assert body["user"]["email"] == "new@auth.example"
        assert "password" not in body["user"]

    async def test_duplicate_email_rejected(self, client: AsyncClient) -> None:
        payload = {
            "email": "dup@auth.example",
            "password": "password12345",
            "display_name": "Dup",
        }
        await client.post("/v1/auth/register", json=payload)
        res = await client.post("/v1/auth/register", json=payload)
        assert res.status_code == 409

    async def test_short_password_rejected(self, client: AsyncClient) -> None:
        res = await client.post(
            "/v1/auth/register",
            json={"email": "short@auth.example", "password": "short", "display_name": "S"},
        )
        assert res.status_code == 422


class TestLogin:
    async def test_login_success(self, client: AsyncClient) -> None:
        await client.post(
            "/v1/auth/register",
            json={
                "email": "login@auth.example",
                "password": "password12345",
                "display_name": "L",
            },
        )
        res = await client.post(
            "/v1/auth/login",
            json={"email": "login@auth.example", "password": "password12345"},
        )
        assert res.status_code == 200
        assert res.json()["tokens"]["access_token"]

    async def test_wrong_password(self, client: AsyncClient) -> None:
        await client.post(
            "/v1/auth/register",
            json={
                "email": "wrong@auth.example",
                "password": "password12345",
                "display_name": "W",
            },
        )
        res = await client.post(
            "/v1/auth/login",
            json={"email": "wrong@auth.example", "password": "not-the-password"},
        )
        assert res.status_code == 401

    async def test_unknown_email_same_error(self, client: AsyncClient) -> None:
        """Unknown email and wrong password must be indistinguishable."""
        unknown = await client.post(
            "/v1/auth/login",
            json={"email": "ghost@auth.example", "password": "whatever-long"},
        )
        assert unknown.status_code == 401
        assert unknown.json()["type"].endswith("/invalid_credentials")


class TestRefreshRotation:
    async def _register(self, client: AsyncClient) -> str:
        res = await client.post(
            "/v1/auth/register",
            json={
                "email": "rot@auth.example",
                "password": "password12345",
                "display_name": "R",
            },
        )
        return res.json()["tokens"]["refresh_token"]

    async def test_rotation_mints_new_pair(self, client: AsyncClient) -> None:
        refresh_token = await self._register(client)
        res = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert res.status_code == 200
        new_tokens = res.json()
        assert new_tokens["refresh_token"] != refresh_token

        # Old token is dead; new one works
        replay = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert replay.status_code == 401
        chained = await client.post("/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
        assert chained.status_code == 200

    async def test_reuse_revokes_chain(self, client: AsyncClient) -> None:
        """Replaying a rotated token kills the whole session (theft response)."""
        refresh_token = await self._register(client)
        first = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
        rotated = first.json()["refresh_token"]

        # Replay the ORIGINAL after rotation (outside grace ⇒ theft signal)
        import asyncio

        await asyncio.sleep(11)  # exceed SYNAPSE_REFRESH_REUSE_GRACE_SECONDS default
        replay = await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert replay.status_code == 401
        assert replay.json()["type"].endswith("/token_reuse_detected")

        # The rotated successor must now also be dead
        dead = await client.post("/v1/auth/refresh", json={"refresh_token": rotated})
        assert dead.status_code == 401


class TestMe:
    async def test_me_lists_orgs(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
        )
        assert res.status_code == 200
        body = res.json()
        assert len(body["orgs"]) == 1
        assert body["orgs"][0]["slug"] == "test-org"
        assert "owner" in body["orgs"][0]["role_keys"]

    async def test_me_requires_auth(self, client: AsyncClient) -> None:
        res = await client.get("/v1/auth/me")
        assert res.status_code == 401
