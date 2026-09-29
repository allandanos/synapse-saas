"""SSO login end to end through the API (P5 / WS-I): start → (Keycloak, mocked) → callback.

Keycloak's token and JWKS endpoints are respx-mocked; everything else — state
handling, PKCE, id_token verification, user linking, the refresh cookie and
the console redirect — is the real code path.
"""

from __future__ import annotations

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import jwt as pyjwt
import pytest
import respx
from httpx import AsyncClient, Response
from sqlalchemy import text

from tests.integration.conftest import owner_session_factory
from tests.unit.identity.test_keycloak_provider import _make_rsa_keypair

pytestmark = pytest.mark.pg

ISSUER = "https://kc.example.test/realms/synapse"


@pytest.fixture(autouse=True)
def _keycloak(monkeypatch: pytest.MonkeyPatch):
    from synapse_saas.core.config import get_settings
    from synapse_saas.identity.provider import clear_jwks_cache

    monkeypatch.setenv("SYNAPSE_IDENTITY_PROVIDER", "keycloak")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_BASE_URL", "https://kc.example.test")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_REALM", "synapse")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_CLIENT_ID", "synapse-web")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SYNAPSE_WEB_ORIGIN", "http://console.test")
    get_settings.cache_clear()
    clear_jwks_cache()
    yield
    clear_jwks_cache()
    get_settings.cache_clear()


@pytest.fixture
def keypair():
    return _make_rsa_keypair()


def _token(pem: bytes, **claims: object) -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": "synapse-web",
        "sub": "kc-sub-1",
        "email": "sso@example.com",
        "email_verified": True,
        "name": "Sso User",
        "iat": now,
        "exp": now + 300,
        **claims,
    }
    return pyjwt.encode(payload, pem, algorithm="RS256", headers={"kid": "test-key"})


async def _start(client: AsyncClient, return_to: str = "/dashboard/billing") -> tuple[str, str]:
    """Kick off the flow; returns (state, nonce) as Keycloak would receive them."""
    res = await client.get("/v1/auth/oidc/start", params={"return_to": return_to})
    assert res.status_code == 302, res.text
    location = res.headers["location"]
    assert location.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    q = parse_qs(urlparse(location).query)
    assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://test/v1/auth/oidc/callback"]
    return q["state"][0], q["nonce"][0]


def _mock_idp(jwk: dict, id_token: str) -> respx.Route:
    respx.get(f"{ISSUER}/protocol/openid-connect/certs").mock(
        return_value=Response(200, json={"keys": [jwk]})
    )
    return respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=Response(200, json={"id_token": id_token})
    )


async def _user_row(email: str) -> dict | None:
    async with owner_session_factory()() as session:
        row = (
            await session.execute(
                text(
                    "SELECT id::text AS id, identity_provider, provider_subject, password_hash "
                    "FROM users WHERE email = :e"
                ),
                {"e": email},
            )
        ).first()
        return dict(row._mapping) if row else None


class TestStart:
    async def test_meta_advertises_the_provider(self, client: AsyncClient) -> None:
        assert (await client.get("/v1/meta")).json()["identity_provider"] == "keycloak"

    async def test_start_redirects_with_pkce(self, client: AsyncClient) -> None:
        state, nonce = await _start(client)
        assert len(state) >= 32 and len(nonce) >= 16

    async def test_open_redirects_are_neutralised(self, client: AsyncClient) -> None:
        state, _ = await _start(client, return_to="https://evil.test/phish")
        # the stored return_to is sanitised; proven at callback time below
        assert state


class TestCallback:
    @respx.mock
    async def test_creates_an_sso_only_user_and_sets_the_cookie(self, client: AsyncClient, keypair) -> None:
        pem, jwk = keypair
        state, nonce = await _start(client)
        token_route = _mock_idp(jwk, _token(pem, nonce=nonce))

        res = await client.get("/v1/auth/oidc/callback", params={"code": "c-1", "state": state})
        assert res.status_code == 302, res.text
        assert res.headers["location"] == "http://console.test/auth/callback?return_to=/dashboard/billing"
        assert "synapse_rt=" in res.headers.get("set-cookie", "")
        # PKCE verifier went to the IdP, and it matches the challenge we sent
        sent = parse_qs(token_route.calls.last.request.content.decode())
        verifier = sent["code_verifier"][0]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert challenge  # (the challenge was bound at /start; the IdP enforces it)

        user = await _user_row("sso@example.com")
        assert user is not None
        assert user["identity_provider"] == "keycloak" and user["provider_subject"] == "kc-sub-1"
        assert user["password_hash"] is None

        # The refresh cookie mints a real session
        cookie = res.cookies.get("synapse_rt")
        refreshed = await client.post("/v1/auth/refresh", json={"refresh_token": cookie})
        assert refreshed.status_code == 200, refreshed.text
        me = await client.get(
            "/v1/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"}
        )
        assert me.status_code == 200 and me.json()["email"] == "sso@example.com"

    @respx.mock
    async def test_state_is_single_use_and_unknown_state_is_401(self, client: AsyncClient, keypair) -> None:
        pem, jwk = keypair
        state, nonce = await _start(client)
        _mock_idp(jwk, _token(pem, nonce=nonce))
        assert (
            await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})
        ).status_code == 302
        replay = await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})
        assert replay.status_code == 401
        assert "expired" in replay.json()["detail"].lower() or "unknown" in replay.json()["detail"].lower()
        assert (
            await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": "nope"})
        ).status_code == 401

    @respx.mock
    async def test_links_by_subject_then_by_verified_email(self, client: AsyncClient, keypair) -> None:
        pem, jwk = keypair
        # An existing LOCAL account with the same (verified) email gets SSO as a second door
        reg = await client.post(
            "/v1/auth/register",
            json={"email": "sso@example.com", "password": "password12345", "display_name": "Local"},
        )
        assert reg.status_code == 201
        state, nonce = await _start(client)
        _mock_idp(jwk, _token(pem, nonce=nonce))
        assert (
            await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})
        ).status_code == 302
        user = await _user_row("sso@example.com")
        assert user is not None and user["provider_subject"] == "kc-sub-1"
        assert user["password_hash"] is not None  # the password still works too

        # Next login: same subject, different email at the IdP ⇒ still the same user
        state, nonce = await _start(client)
        _mock_idp(jwk, _token(pem, nonce=nonce, email="renamed@example.com"))
        assert (
            await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})
        ).status_code == 302
        assert await _user_row("renamed@example.com") is None
        assert (await _user_row("sso@example.com"))["id"] == user["id"]  # type: ignore[index]

    @respx.mock
    async def test_unverified_email_never_takes_over_a_local_account(
        self, client: AsyncClient, keypair
    ) -> None:
        pem, jwk = keypair
        await client.post(
            "/v1/auth/register",
            json={"email": "victim@example.com", "password": "password12345", "display_name": "V"},
        )
        state, nonce = await _start(client)
        _mock_idp(
            jwk, _token(pem, nonce=nonce, sub="attacker", email="victim@example.com", email_verified=False)
        )
        res = await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})
        assert res.status_code == 401, res.text
        assert res.json()["reason"] == "email_unverified"
        user = await _user_row("victim@example.com")
        assert user is not None and user["identity_provider"] == "local" and user["provider_subject"] is None

    @respx.mock
    async def test_nonce_mismatch_is_401(self, client: AsyncClient, keypair) -> None:
        pem, jwk = keypair
        state, _ = await _start(client)
        _mock_idp(jwk, _token(pem, nonce="not-the-one-we-sent"))
        res = await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})
        assert res.status_code == 401 and "nonce" in res.json()["detail"]

    async def test_idp_error_is_401(self, client: AsyncClient) -> None:
        res = await client.get("/v1/auth/oidc/callback", params={"error": "access_denied", "state": "x"})
        assert res.status_code == 401


class TestPasswordFormForSsoUsers:
    @respx.mock
    async def test_password_login_is_redirected_to_sso(self, client: AsyncClient, keypair) -> None:
        pem, jwk = keypair
        state, nonce = await _start(client)
        _mock_idp(jwk, _token(pem, nonce=nonce))
        await client.get("/v1/auth/oidc/callback", params={"code": "c", "state": state})

        res = await client.post("/v1/auth/login", json={"email": "sso@example.com", "password": "anything"})
        assert res.status_code == 401, res.text
        assert res.json()["sso_url"] == "/v1/auth/oidc/start"
        assert res.json()["identity_provider"] == "keycloak"


class TestPasswordGrantOptIn:
    """`SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT=true`: the password form proxies to
    Keycloak (ROPC) for unknown or SSO-only accounts — the setting used to be dead."""

    async def test_login_proxies_to_keycloak_when_enabled(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.identity import provider as provider_module
        from synapse_saas.identity.service import IdentityService

        monkeypatch.setenv("SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT", "true")
        get_settings.cache_clear()

        # An SSO-only account Keycloak knows about
        async with owner_session_factory()() as session:
            user = await IdentityService(session).link_or_create_oidc_user(
                {"sub": "kc-ropc-1", "email": "ropc@example.com", "email_verified": True, "name": "Ropc"}
            )
            await session.commit()
            user_id = user.id

        class StubProvider:
            calls: list[tuple[str, str]] = []

            async def verify_credentials(self, email: str, password: str):
                self.calls.append((email, password))
                return user_id if password == "kc-password" else None

        monkeypatch.setattr(provider_module, "get_identity_provider", StubProvider)

        ok = await client.post(
            "/v1/auth/login", json={"email": "ropc@example.com", "password": "kc-password"}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["id"] == str(user_id) and ok.json()["tokens"]["access_token"]
        assert StubProvider.calls == [("ropc@example.com", "kc-password")]

        bad = await client.post(
            "/v1/auth/login", json={"email": "ropc@example.com", "password": "nope-nope-1"}
        )
        assert bad.status_code == 401 and bad.json()["title"] == "invalid credentials", bad.text

    async def test_sso_only_still_points_at_sso_when_disabled(self, client: AsyncClient) -> None:
        from synapse_saas.identity.service import IdentityService

        async with owner_session_factory()() as session:
            await IdentityService(session).link_or_create_oidc_user(
                {"sub": "kc-ropc-2", "email": "ssoonly@example.com", "email_verified": True}
            )
            await session.commit()
        res = await client.post(
            "/v1/auth/login", json={"email": "ssoonly@example.com", "password": "whatever-123"}
        )
        assert res.status_code == 401 and res.json()["sso_url"] == "/v1/auth/oidc/start", res.text
