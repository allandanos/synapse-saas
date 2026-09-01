"""Password hashing and JWT helpers.

- argon2id for passwords (hardened against GPU attacks, memory-hard)
- HS256 JWTs for short-lived access tokens (stateless, org claim optional)
- Opaque, high-entropy refresh tokens stored hashed (sha256) at rest
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import AuthenticationError

_password_hasher = PasswordHasher()  # argon2id defaults: t=3, m=64MiB, p=4

ALGORITHM = "HS256"
ISSUER = "synapse-saas"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


# ── Access tokens (JWT) ────────────────────────────────────────────────────────


def create_access_token(
    user_id: UUID,
    *,
    email: str,
    organization_id: UUID | None = None,
    is_platform_admin: bool = False,
    ttl_seconds: int | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds or settings.access_token_ttl_seconds)).timestamp()),
        "iss": ISSUER,
        "type": "access",
    }
    if organization_id is not None:
        payload["org"] = str(organization_id)
    if is_platform_admin:
        payload["platform_admin"] = True
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + validate. Raises AuthenticationError on any failure (never leaks which check failed)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[ALGORITHM],  # pinned: refuse alg=none / RS256-confusion
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Access token is invalid or expired") from exc
    if payload.get("type") != "access":
        raise AuthenticationError("Access token is invalid or expired")
    return payload


# ── Refresh tokens (opaque) ────────────────────────────────────────────────────

REFRESH_TOKEN_BYTES = 32


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Shared-secret / signature helpers ─────────────────────────────────────────


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def sign_payload(payload: bytes, secret: str, *, timestamp: int) -> str:
    """Stripe-style v1 signature: HMAC_SHA256(f"{timestamp}.{payload}", secret)."""
    signed = f"{timestamp}.".encode() + payload
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def verify_signature(payload: bytes, secret: str, *, timestamp: int, signature: str) -> bool:
    expected = sign_payload(payload, secret, timestamp=timestamp)
    return constant_time_equals(expected, signature)
