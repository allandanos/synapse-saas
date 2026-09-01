"""Identity provider abstraction.

`IdentityProvider` is the seam: local email/password today, Keycloak OIDC when
an org needs SSO — the service layer never knows which is active.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import httpx

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import AuthenticationError
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)


class IdentityProvider(Protocol):
    """What the identity service needs from any auth backend."""

    name: str

    async def verify_credentials(self, email: str, password: str) -> UUID | None:
        """Return the user id on success, None on bad credentials."""
        ...

    async def exchange_oidc_code(self, code: str, *, redirect_uri: str) -> tuple[str, dict[str, Any]]:
        """Exchange an authorization code for (id_token, claims)."""
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

    async def exchange_oidc_code(self, code: str, *, redirect_uri: str) -> tuple[str, dict[str, Any]]:
        raise AuthenticationError("OIDC is not available with the local identity provider")


# Pre-computed argon2 hash of an unguessable string — burns the same CPU on
# login attempts against nonexistent emails, preventing user enumeration by timing.
DUMMY_ARGON2_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$c2NybU5vdEFSZWFsUGFzc3dvcmQ$bQ9OBGPOtW4Kpl6Z73pQ4Lc2v1OiqeuCYiY0FbxBNCs"
)


class KeycloakOIDCProvider:
    """Keycloak adapter — enabled via SYNAPSE_IDENTITY_PROVIDER=keycloak.

    Verifies tokens against the realm JWKS; users are JIT-provisioned on first
    login with `identity_provider=keycloak` and no local password.
    """

    name = "keycloak"

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    def _config(self) -> tuple[str, str, str, str]:
        settings = get_settings()
        if not (settings.keycloak_base_url and settings.keycloak_realm):
            raise AuthenticationError("Keycloak is not configured")
        return (
            settings.keycloak_base_url,
            settings.keycloak_realm,
            settings.keycloak_client_id,
            settings.keycloak_client_secret,
        )

    async def verify_credentials(self, email: str, password: str) -> UUID | None:
        """Resource-owner password grant against Keycloak → local user id."""
        import jwt

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.identity.service import IdentityService

        base_url, realm, client_id, client_secret = self._config()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/realms/{realm}/protocol/openid-connect/token",
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

        claims = jwt.decode(
            response.json()["id_token"],
            options={"verify_signature": False},  # signature verified below via JWKS
            algorithms=["RS256"],
        )
        subject = claims.get("sub")
        if not subject:
            return None

        async with get_session_factory()() as session:
            service = IdentityService(session)
            user = await service.upsert_oidc_user(
                email=claims.get("email") or email,
                display_name=claims.get("name") or email,
                provider_subject=subject,
            )
            return user.id if user and user.is_active else None

    async def exchange_oidc_code(self, code: str, *, redirect_uri: str) -> tuple[str, dict[str, Any]]:
        """Authorization-code flow callback → (id_token, verified_claims)."""
        import jwt as pyjwt

        base_url, realm, client_id, client_secret = self._config()
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(
                f"{base_url}/realms/{realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            if token_response.status_code != 200:
                raise AuthenticationError("OIDC code exchange failed")
            jwks_response = await client.get(f"{base_url}/realms/{realm}/protocol/openid-connect/certs")
            jwks_response.raise_for_status()

        id_token = token_response.json()["id_token"]
        jwks = jwks_response.json()
        signing_key = self._signing_key_for(id_token, jwks)
        claims = pyjwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
        )
        return id_token, claims

    @staticmethod
    def _signing_key_for(id_token: str, jwks: dict[str, Any]) -> Any:
        """Pick the JWKS key whose kid matches the token header.

        Returns the key object pyjwt accepts (a cryptography public key), not a string.
        """
        import jwt as pyjwt
        from jwt import PyJWK

        header = pyjwt.get_unverified_header(id_token)
        kid = header.get("kid")
        for jwk_data in jwks.get("keys", []):
            if jwk_data.get("kid") == kid:
                return PyJWK.from_dict(jwk_data, algorithm="RS256").key
        raise AuthenticationError("No matching Keycloak signing key for token")


def get_identity_provider() -> IdentityProvider:
    settings = get_settings()
    if settings.identity_provider == "keycloak":
        return KeycloakOIDCProvider()
    return LocalIdentityProvider()
