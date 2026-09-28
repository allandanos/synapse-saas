"""Identity provider abstraction.

`IdentityProvider` is the seam: local email/password today, Keycloak OIDC when
an org needs SSO — the service layer never knows which is active.

OIDC login (Keycloak) is the authorization-code flow with PKCE:
`authorization_url()` starts it, `exchange_oidc_code()` finishes it, and the
id_token is verified against the realm's JWKS (cached, refetched on an unknown
`kid`) for signature, issuer, audience and nonce.
"""

from __future__ import annotations

import time
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import UUID

import httpx

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import AuthenticationError
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)

JWKS_TTL_SECONDS = 3600


class IdentityProvider(Protocol):
    """What the identity service needs from any auth backend."""

    name: str

    async def verify_credentials(self, email: str, password: str) -> UUID | None:
        """Return the user id on success, None on bad credentials."""
        ...

    def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        """Where to send the browser to start an OIDC login."""
        ...

    async def exchange_oidc_code(
        self,
        code: str,
        *,
        redirect_uri: str,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Exchange an authorization code for (id_token, verified claims)."""
        ...


class LocalIdentityProvider:
    """Built-in email/password auth. Default — zero external dependencies."""

    name = "local"

    def __init__(self, verifier: object = None) -> None:
        # verifier injected for tests; default = argon2 verify against DB hash
        self._verifier = verifier

    async def verify_credentials(self, email: str, password: str) -> UUID | None:
        from sqlalchemy import select

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.core.security import verify_password
        from synapse_saas.identity.models import User

        async with get_session_factory()() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is None or user.password_hash is None or not user.is_active:
                # Constant-ish work even for unknown emails
                verify_password(password, DUMMY_ARGON2_HASH)
                return None
            if not verify_password(password, user.password_hash):
                return None
            return user.id

    def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        raise AuthenticationError("SSO is not available with the local identity provider")

    async def exchange_oidc_code(
        self,
        code: str,
        *,
        redirect_uri: str,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        raise AuthenticationError("OIDC is not available with the local identity provider")


# Pre-computed argon2 hash of an unguessable string — burns the same CPU on
# login attempts against nonexistent emails, preventing user enumeration by timing.
DUMMY_ARGON2_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$c2NybU5vdEFSZWFsUGFzc3dvcmQ$bQ9OBGPOtW4Kpl6Z73pQ4Lc2v1OiqeuCYiY0FbxBNCs"
)

# issuer -> (fetched_at, jwks)
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_jwks_cache() -> None:
    _JWKS_CACHE.clear()


class KeycloakOIDCProvider:
    """Keycloak adapter — enabled via SYNAPSE_IDENTITY_PROVIDER=keycloak.

    Browser logins use the authorization-code flow with PKCE
    (`/v1/auth/oidc/start` → Keycloak → `/v1/auth/oidc/callback`). Users are
    linked by `provider_subject`, else by a *verified* email, else created with
    `identity_provider=keycloak` and no local password.
    """

    name = "keycloak"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    def _config(self) -> tuple[str, str, str, str]:
        settings = get_settings()
        if not (settings.keycloak_base_url and settings.keycloak_realm):
            raise AuthenticationError("Keycloak is not configured")
        return (
            settings.keycloak_base_url.rstrip("/"),
            settings.keycloak_realm,
            settings.keycloak_client_id,
            settings.keycloak_client_secret,
        )

    @property
    def issuer(self) -> str:
        base_url, realm, _, _ = self._config()
        return f"{base_url}/realms/{realm}"

    def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=10)

    # ── Authorization-code flow ─────────────────────────────────────────────────

    def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        _, _, client_id, _ = self._config()
        query = urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "scope": "openid email profile",
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self.issuer}/protocol/openid-connect/auth?{query}"

    async def exchange_oidc_code(
        self,
        code: str,
        *,
        redirect_uri: str,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Authorization-code callback → (id_token, verified claims).

        Verifies: RS256 signature against the realm JWKS (cached one hour,
        refetched once on an unknown kid), `iss`, `aud`, expiry, and the
        `nonce` bound to this login attempt.
        """
        import jwt as pyjwt

        _, _, client_id, client_secret = self._config()
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        client = self._client()
        try:
            token_response = await client.post(f"{self.issuer}/protocol/openid-connect/token", data=data)
            if token_response.status_code != 200:
                logger.info("oidc_code_exchange_failed", status=token_response.status_code)
                raise AuthenticationError("OIDC code exchange failed")
            id_token = str(token_response.json().get("id_token") or "")
            if not id_token:
                raise AuthenticationError("OIDC token response carried no id_token")
            signing_key = await self._signing_key(client, id_token)
        finally:
            if self._http is None:
                await client.aclose()

        try:
            claims: dict[str, Any] = pyjwt.decode(
                id_token,
                signing_key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except pyjwt.PyJWTError as exc:
            logger.info("oidc_id_token_rejected", error=str(exc))
            raise AuthenticationError(f"OIDC id_token rejected: {exc}") from exc
        if nonce is not None and claims.get("nonce") != nonce:
            raise AuthenticationError("OIDC nonce mismatch")
        return id_token, claims

    async def _signing_key(self, client: httpx.AsyncClient, id_token: str) -> Any:
        import jwt as pyjwt
        from jwt import PyJWK

        kid = pyjwt.get_unverified_header(id_token).get("kid")
        for attempt in ("cached", "refetched"):
            jwks = await self._jwks(client, force=attempt == "refetched")
            for jwk_data in jwks.get("keys", []):
                if jwk_data.get("kid") == kid:
                    return PyJWK.from_dict(jwk_data, algorithm="RS256").key
        raise AuthenticationError("No matching Keycloak signing key for token")

    async def _jwks(self, client: httpx.AsyncClient, *, force: bool = False) -> dict[str, Any]:
        cached = _JWKS_CACHE.get(self.issuer)
        if cached and not force and time.monotonic() - cached[0] < JWKS_TTL_SECONDS:
            return cached[1]
        response = await client.get(f"{self.issuer}/protocol/openid-connect/certs")
        response.raise_for_status()
        jwks: dict[str, Any] = response.json()
        _JWKS_CACHE[self.issuer] = (time.monotonic(), jwks)
        return jwks

    # ── Resource-owner password grant (opt-in) ──────────────────────────────────

    async def verify_credentials(self, email: str, password: str) -> UUID | None:
        """Email+password proxied to Keycloak. Off unless
        SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT=true — the code flow is the default."""
        if not get_settings().keycloak_allow_password_grant:
            return None
        import jwt as pyjwt

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.identity.service import IdentityService

        _, _, client_id, client_secret = self._config()
        client = self._client()
        try:
            response = await client.post(
                f"{self.issuer}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": email,
                    "password": password,
                    "scope": "openid",
                },
            )
            if response.status_code != 200:
                return None
            id_token = str(response.json().get("id_token") or "")
            signing_key = await self._signing_key(client, id_token)
        finally:
            if self._http is None:
                await client.aclose()
        try:
            claims = pyjwt.decode(
                id_token, signing_key, algorithms=["RS256"], audience=client_id, issuer=self.issuer
            )
        except pyjwt.PyJWTError:
            return None
        async with get_session_factory()() as session:
            user = await IdentityService(session).link_or_create_oidc_user(claims)
            await session.commit()
            return user.id if user.is_active else None


def get_identity_provider() -> IdentityProvider:
    settings = get_settings()
    if settings.identity_provider == "keycloak":
        return KeycloakOIDCProvider()
    return LocalIdentityProvider()
