"""Auth flow: register → login → refresh rotation → reuse detection → logout."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient, Response

from tests.integration.test_api_keys import _add_member

pytestmark = pytest.mark.pg


async def _me(client: AsyncClient, tokens: dict[str, str]) -> dict:
    res = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 200, res.text
    return res.json()


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

    async def test_me_carries_permission_keys_per_org(self, client: AsyncClient, org_and_tokens) -> None:
        """Owner and member each see their own effective RBAC set, sorted."""
        member = await _add_member(client, org_and_tokens, "reader@auth.example", "member")

        owner_org = (await _me(client, org_and_tokens))["orgs"][0]
        owner_keys = owner_org["permission_keys"]
        assert owner_keys == sorted(owner_keys)
        assert {"org:read", "member:read", "billing:read", "org:delete"} <= set(owner_keys)
        assert "entitlement:manage" not in owner_keys

        member_org = (await _me(client, member))["orgs"][0]
        assert member_org["role_keys"] == ["member"]
        assert member_org["permission_keys"] == ["member:read", "org:read", "project:read"]

    async def test_me_requires_auth(self, client: AsyncClient) -> None:
        res = await client.get("/v1/auth/me")
        assert res.status_code == 401


class TestPreferences:
    """`PATCH /v1/auth/me`: top-level merge into the caller's own `users.preferences`."""

    @staticmethod
    def _bearer(fixture: dict[str, str]) -> dict[str, str]:
        return {"Authorization": f"Bearer {fixture['access_token']}"}

    async def _patch(self, client: AsyncClient, fixture: dict[str, str], prefs: object) -> Response:
        return await client.patch("/v1/auth/me", headers=self._bearer(fixture), json={"preferences": prefs})

    async def test_empty_by_default(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/auth/me", headers=self._bearer(org_and_tokens))
        assert res.status_code == 200
        assert res.json()["preferences"] == {}

    async def test_merge_keeps_earlier_keys_and_returns_the_me_shape(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        tours = {"console-welcome": {"status": "completed", "version": 1}}
        first = await self._patch(client, org_and_tokens, {"tours": tours})
        assert first.status_code == 200, first.text
        second = await self._patch(client, org_and_tokens, {"sidebar_collapsed": True})
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["preferences"] == {"tours": tours, "sidebar_collapsed": True}
        assert body["orgs"][0]["role_keys"] == ["owner"]
        me = await client.get("/v1/auth/me", headers=self._bearer(org_and_tokens))
        assert me.json()["preferences"] == body["preferences"]

    async def test_a_listed_key_is_replaced_wholesale(self, client: AsyncClient, org_and_tokens) -> None:
        await self._patch(client, org_and_tokens, {"tours": {"a": {"status": "skipped"}}, "theme": "x"})
        res = await self._patch(client, org_and_tokens, {"tours": {}})
        assert res.json()["preferences"] == {"tours": {}, "theme": "x"}

    async def test_empty_body_is_a_no_op(self, client: AsyncClient, org_and_tokens) -> None:
        await self._patch(client, org_and_tokens, {"theme": "x"})
        res = await client.patch("/v1/auth/me", headers=self._bearer(org_and_tokens), json={})
        assert res.status_code == 200, res.text
        assert res.json()["preferences"] == {"theme": "x"}

    async def test_bad_key_is_422(self, client: AsyncClient, org_and_tokens) -> None:
        res = await self._patch(client, org_and_tokens, {"Tours": {}})
        assert res.status_code == 422
        assert res.json()["type"].endswith("/validation_failed")

    @pytest.mark.parametrize(
        "raw",
        ['{"preferences":{"a":NaN}}', '{"preferences":{"a":1e999}}', '{"preferences":{"a":"\\u0000"}}'],
    )
    async def test_hostile_json_values_are_422(self, client: AsyncClient, org_and_tokens, raw: str) -> None:
        # Python's json accepts NaN/1e999 and JSONB refuses NUL: all three must stop at validation.
        headers = {**self._bearer(org_and_tokens), "Content-Type": "application/json"}
        res = await client.patch("/v1/auth/me", headers=headers, content=raw)
        assert res.status_code == 422, res.text
        assert res.json()["type"].endswith("/validation_failed")

    async def test_pathological_nesting_is_422(self, client: AsyncClient, org_and_tokens) -> None:
        headers = {**self._bearer(org_and_tokens), "Content-Type": "application/json"}
        raw = '{"preferences":{"a":' + "[" * 600 + "]" * 600 + "}}"
        res = await client.patch("/v1/auth/me", headers=headers, content=raw)
        assert res.status_code == 422, res.text
        assert res.json()["type"].endswith("/validation_failed")

    async def test_concurrent_patches_of_different_keys_both_land(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        # Two tabs saving at once: the row is locked and re-read, so neither merge overwrites the other.
        first, second = await asyncio.gather(
            self._patch(client, org_and_tokens, {"tours": {"a": {"status": "completed"}}}),
            self._patch(client, org_and_tokens, {"theme": "dark"}),
        )
        assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
        me = await client.get("/v1/auth/me", headers=self._bearer(org_and_tokens))
        assert me.json()["preferences"] == {"tours": {"a": {"status": "completed"}}, "theme": "dark"}

    async def test_oversized_patch_is_422(self, client: AsyncClient, org_and_tokens) -> None:
        res = await self._patch(client, org_and_tokens, {"big": "x" * 17 * 1024})
        assert res.status_code == 422
        assert res.json()["type"].endswith("/validation_failed")

    async def test_stored_cap_is_enforced_across_requests(self, client: AsyncClient, org_and_tokens) -> None:
        chunk = "x" * 12 * 1024
        for key in ("a", "b"):
            ok = await self._patch(client, org_and_tokens, {key: chunk})
            assert ok.status_code == 200, ok.text
        over = await self._patch(client, org_and_tokens, {"c": chunk})
        assert over.status_code == 422
        assert over.json()["type"].endswith("/validation_failed")
        me = await client.get("/v1/auth/me", headers=self._bearer(org_and_tokens))
        assert set(me.json()["preferences"]) == {"a", "b"}

    async def test_other_users_are_unaffected(self, client: AsyncClient, org_and_tokens) -> None:
        await self._patch(client, org_and_tokens, {"theme": "x"})
        other = await client.post(
            "/v1/auth/register",
            json={"email": "other@prefs.example", "password": "password12345", "display_name": "Other"},
        )
        token = other.json()["tokens"]["access_token"]
        me = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["preferences"] == {}

    async def test_requires_a_bearer(self, client: AsyncClient) -> None:
        res = await client.patch("/v1/auth/me", json={"preferences": {"theme": "x"}})
        assert res.status_code == 401

    async def test_api_keys_are_forbidden(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/api-keys",
            headers={**self._bearer(org_and_tokens), "X-Org-Id": org_and_tokens["org_id"]},
            json={"name": "prefs"},
        )
        assert res.status_code == 201, res.text
        key = res.json()["key"]
        denied = await client.patch(
            "/v1/auth/me", headers={"Authorization": f"Bearer {key}"}, json={"preferences": {"theme": "x"}}
        )
        assert denied.status_code == 403, denied.text
        assert denied.json()["type"].endswith("/permission_denied")
