"""Keycloak identity provider via respx — token grant + JWKS verification."""

from __future__ import annotations

import base64

import httpx
import jwt as pyjwt
import pytest
import respx
from httpx import Response

from synapse_saas.core.errors import AuthenticationError
from synapse_saas.identity.provider import KeycloakOIDCProvider, get_identity_provider

pytestmark = pytest.mark.asyncio

ISSUER = "https://kc.example.test/realms/synapse"


@pytest.fixture(autouse=True)
def _keycloak_config(monkeypatch: pytest.MonkeyPatch):
    from synapse_saas.core.config import get_settings

    monkeypatch.setenv("SYNAPSE_IDENTITY_PROVIDER", "keycloak")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_BASE_URL", "https://kc.example.test")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_REALM", "synapse")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_CLIENT_ID", "synapse-web")
    monkeypatch.setenv("SYNAPSE_KEYCLOAK_CLIENT_SECRET", "secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    jwk = private_key.public_key().public_numbers()
    n = jwk.n.to_bytes((jwk.n.bit_length() + 7) // 8, "big")
    e = jwk.e.to_bytes((jwk.e.bit_length() + 7) // 8, "big")
    return pem, {
        "kty": "RSA",
        "kid": "test-key",
        "n": base64.urlsafe_b64encode(n).decode().rstrip("="),
        "e": base64.urlsafe_b64encode(e).decode().rstrip("="),
    }


@pytest.fixture
def keypair():
    return _make_rsa_keypair()


class TestProviderSelection:
    def test_keycloak_selected(self) -> None:
        assert get_identity_provider().name == "keycloak"

    def test_local_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_IDENTITY_PROVIDER", "local")
        get_settings.cache_clear()
        assert get_identity_provider().name == "local"
        get_settings.cache_clear()


def _id_token(pem: str | bytes, **claims: object) -> str:
    import time as _time

    now = int(_time.time())
    payload = {
        "iss": ISSUER,
        "aud": "synapse-web",
        "sub": "kc-user-1",
        "email": "kc@example.com",
        "email_verified": True,
        "iat": now,
        "exp": now + 300,
        **claims,
    }
    return pyjwt.encode(payload, pem, algorithm="RS256", headers={"kid": "test-key"})


def _mock_idp(jwk: dict, id_token: str) -> respx.Route:
    respx.get(f"{ISSUER}/protocol/openid-connect/certs").mock(
        return_value=Response(200, json={"keys": [jwk]})
    )
    return respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
        return_value=Response(200, json={"id_token": id_token})
    )


@pytest.fixture(autouse=True)
def _fresh_jwks_cache():
    from synapse_saas.identity.provider import clear_jwks_cache

    clear_jwks_cache()
    yield
    clear_jwks_cache()


class TestAuthorizationUrl:
    def test_carries_pkce_state_and_nonce(self) -> None:
        url = KeycloakOIDCProvider().authorization_url(
            redirect_uri="https://api.example.test/v1/auth/oidc/callback",
            state="st",
            nonce="nn",
            code_challenge="chal",
        )
        assert url.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
        assert "client_id=synapse-web" in url
        assert "response_type=code" in url
        assert "code_challenge=chal" in url and "code_challenge_method=S256" in url
        assert "state=st" in url and "nonce=nn" in url
        assert "redirect_uri=https%3A%2F%2Fapi.example.test%2Fv1%2Fauth%2Foidc%2Fcallback" in url


class TestExchangeOidcCode:
    @respx.mock
    async def test_exchange_verifies_signature_issuer_audience_and_nonce(self, keypair) -> None:
        pem, jwk = keypair
        token_route = _mock_idp(jwk, _id_token(pem, nonce="n-1"))

        provider = KeycloakOIDCProvider(httpx.AsyncClient())
        _, claims = await provider.exchange_oidc_code(
            "code-123", redirect_uri="https://app.example.test/callback", code_verifier="ver-1", nonce="n-1"
        )
        assert claims["sub"] == "kc-user-1"
        assert claims["email"] == "kc@example.com"
        sent = token_route.calls.last.request.content.decode()
        assert "code_verifier=ver-1" in sent and "grant_type=authorization_code" in sent

    @respx.mock
    async def test_rejects_bad_code(self) -> None:
        respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )
        provider = KeycloakOIDCProvider(httpx.AsyncClient())
        with pytest.raises(AuthenticationError):
            await provider.exchange_oidc_code("bad", redirect_uri="https://app.example.test/callback")

    @respx.mock
    async def test_nonce_mismatch_rejected(self, keypair) -> None:
        pem, jwk = keypair
        _mock_idp(jwk, _id_token(pem, nonce="expected"))
        with pytest.raises(AuthenticationError, match="nonce"):
            await KeycloakOIDCProvider(httpx.AsyncClient()).exchange_oidc_code(
                "c", redirect_uri="r", nonce="other"
            )

    @respx.mock
    async def test_wrong_issuer_rejected(self, keypair) -> None:
        pem, jwk = keypair
        _mock_idp(jwk, _id_token(pem, iss="https://evil.example.test/realms/synapse"))
        with pytest.raises(AuthenticationError, match="rejected"):
            await KeycloakOIDCProvider(httpx.AsyncClient()).exchange_oidc_code("c", redirect_uri="r")

    @respx.mock
    async def test_wrong_audience_rejected(self, keypair) -> None:
        pem, jwk = keypair
        _mock_idp(jwk, _id_token(pem, aud="another-client"))
        with pytest.raises(AuthenticationError, match="rejected"):
            await KeycloakOIDCProvider(httpx.AsyncClient()).exchange_oidc_code("c", redirect_uri="r")

    @respx.mock
    async def test_expired_token_rejected(self, keypair) -> None:
        pem, jwk = keypair
        _mock_idp(jwk, _id_token(pem, exp=1))
        with pytest.raises(AuthenticationError, match="rejected"):
            await KeycloakOIDCProvider(httpx.AsyncClient()).exchange_oidc_code("c", redirect_uri="r")

    @respx.mock
    async def test_jwks_is_cached_and_refetched_on_unknown_kid(self, keypair) -> None:
        pem, jwk = keypair
        certs = respx.get(f"{ISSUER}/protocol/openid-connect/certs").mock(
            return_value=Response(200, json={"keys": [jwk]})
        )
        respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
            return_value=Response(200, json={"id_token": _id_token(pem)})
        )
        provider = KeycloakOIDCProvider(httpx.AsyncClient())
        await provider.exchange_oidc_code("c1", redirect_uri="r")
        await provider.exchange_oidc_code("c2", redirect_uri="r")
        assert certs.call_count == 1  # second login served from the cache

        # A rotated key: the token's kid is unknown ⇒ one refetch, then it verifies
        rotated_pem, rotated_jwk = _make_rsa_keypair()
        rotated_jwk = {**rotated_jwk, "kid": "rotated"}
        certs.mock(return_value=Response(200, json={"keys": [jwk, rotated_jwk]}))
        rotated_token = pyjwt.encode(
            {
                "iss": ISSUER,
                "aud": "synapse-web",
                "sub": "kc-user-2",
                "email": "x@example.com",
                "iat": 1,
                "exp": 4102444800,
            },
            rotated_pem,
            algorithm="RS256",
            headers={"kid": "rotated"},
        )
        respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
            return_value=Response(200, json={"id_token": rotated_token})
        )
        _, claims = await provider.exchange_oidc_code("c3", redirect_uri="r")
        assert claims["sub"] == "kc-user-2"
        assert certs.call_count == 2


class TestPasswordGrantIsOptIn:
    async def test_refused_by_default(self) -> None:
        assert await KeycloakOIDCProvider(httpx.AsyncClient()).verify_credentials("a@b.c", "pw") is None


class TestUnconfigured:
    async def test_raises_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_KEYCLOAK_BASE_URL", "")
        get_settings.cache_clear()
        provider = KeycloakOIDCProvider()
        with pytest.raises(AuthenticationError, match="not configured"):
            await provider.exchange_oidc_code("c", redirect_uri="r")
        get_settings.cache_clear()
