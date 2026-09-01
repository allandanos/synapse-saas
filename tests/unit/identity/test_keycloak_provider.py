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


class TestExchangeOidcCode:
    @respx.mock
    async def test_exchange_verifies_signature(self, keypair) -> None:
        pem, jwk = keypair
        id_token = pyjwt.encode(
            {"sub": "kc-user-1", "email": "kc@example.com", "aud": "synapse-web"},
            pem,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
        respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
            return_value=Response(200, json={"id_token": id_token})
        )
        respx.get(f"{ISSUER}/protocol/openid-connect/certs").mock(
            return_value=Response(200, json={"keys": [jwk]})
        )

        provider = KeycloakOIDCProvider(httpx.AsyncClient())
        _, claims = await provider.exchange_oidc_code(
            "code-123", redirect_uri="https://app.example.test/callback"
        )
        assert claims["sub"] == "kc-user-1"
        assert claims["email"] == "kc@example.com"

    @respx.mock
    async def test_rejects_bad_code(self) -> None:
        respx.post(f"{ISSUER}/protocol/openid-connect/token").mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )
        provider = KeycloakOIDCProvider(httpx.AsyncClient())
        with pytest.raises(AuthenticationError):
            await provider.exchange_oidc_code("bad", redirect_uri="https://app.example.test/callback")


class TestUnconfigured:
    async def test_raises_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_KEYCLOAK_BASE_URL", "")
        get_settings.cache_clear()
        provider = KeycloakOIDCProvider()
        with pytest.raises(AuthenticationError, match="not configured"):
            await provider.exchange_oidc_code("c", redirect_uri="r")
        get_settings.cache_clear()
