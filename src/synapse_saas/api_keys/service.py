"""API key domain service.

Security model:
- Plaintext `sk_<32 urlsafe chars>` is generated once, hashed (SHA-256), and
  only the hash is stored. The plaintext returns exactly once at creation.
- `prefix` (first 8 chars) is stored for display ("sk_ab12…") and lookups.
- A key authenticates as its organization with the intersection of its scopes
  and what's exercise — an empty scope list means everything the creator held.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.api_keys.models import ApiKey
from synapse_saas.authorization.permissions import PERMISSION_KEYS
from synapse_saas.core import events
from synapse_saas.core.errors import ApiKeyNotFoundError, PermissionDeniedError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox

logger = get_logger(__name__)

KEY_PREFIX = "sk_"
KEY_RANDOM_BYTES = 32
PREFIX_DISPLAY_LENGTH = 8


def _hash_key(plaintext: str) -> str:
    return sha256(plaintext.encode("utf-8")).hexdigest()


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Management ──────────────────────────────────────────────────────────────

    async def create_key(
        self,
        organization_id: UUID,
        *,
        name: str,
        scopes: list[str],
        expires_in_days: int | None = None,
        created_by_user_id: UUID | None = None,
    ) -> tuple[ApiKey, str]:
        """Create a key. Returns (key, plaintext) — plaintext shown once."""
        unknown = set(scopes) - PERMISSION_KEYS
        if unknown:
            raise PermissionDeniedError(
                f"Unknown permission scopes: {sorted(unknown)}", extras={"unknown": sorted(unknown)}
            )

        plaintext = KEY_PREFIX + secrets.token_urlsafe(KEY_RANDOM_BYTES)
        key = ApiKey(
            organization_id=organization_id,
            name=name,
            prefix=plaintext[:PREFIX_DISPLAY_LENGTH],
            key_hash=_hash_key(plaintext),
            scopes=scopes,
            expires_at=(datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None),
            created_by_user_id=created_by_user_id,
        )
        self.session.add(key)
        await self.session.flush()

        self._audit(
            events.API_KEY_CREATED,
            organization_id=organization_id,
            target_type="api_key",
            target_id=key.id,
            diff={"name": name, "scopes": scopes},
        )
        append_outbox(
            self.session,
            event_type=events.API_KEY_CREATED,
            aggregate_type="api_key",
            aggregate_id=key.id,
            organization_id=organization_id,
            payload={"name": name, "scopes": scopes},
        )
        return key, plaintext

    async def list_keys(self, organization_id: UUID) -> list[ApiKey]:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.organization_id == organization_id).order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_key(self, key_id: UUID, organization_id: UUID) -> ApiKey:
        key = await self._get_scoped(key_id, organization_id)
        key.revoked_at = datetime.now(UTC)
        await self.session.flush()

        self._audit(
            events.API_KEY_REVOKED,
            organization_id=organization_id,
            target_type="api_key",
            target_id=key.id,
        )
        append_outbox(
            self.session,
            event_type=events.API_KEY_REVOKED,
            aggregate_type="api_key",
            aggregate_id=key.id,
            organization_id=organization_id,
            payload={"name": key.name},
        )
        return key

    # ── Verification ────────────────────────────────────────────────────────────

    async def verify(self, plaintext: str) -> ApiKey | None:
        """Resolve a plaintext key to its active row, or None.

        Callers must treat None as opaque 401 material — never reveal whether
        the key existed, was revoked, or expired.
        """
        if not plaintext.startswith(KEY_PREFIX):
            return None
        key = (
            await self.session.execute(select(ApiKey).where(ApiKey.key_hash == _hash_key(plaintext)))
        ).scalar_one_or_none()
        if key is None or not key.is_active:
            return None

        key.last_used_at = datetime.now(UTC)
        return key

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _get_scoped(self, key_id: UUID, organization_id: UUID) -> ApiKey:
        key = await self.session.get(ApiKey, key_id)
        if key is None or key.organization_id != organization_id:
            raise ApiKeyNotFoundError("API key not found")  # 404 cross-tenant
        return key

    def _audit(
        self,
        event_type: str,
        *,
        organization_id: UUID,
        target_type: str | None,
        target_id: UUID | None,
        diff: dict[str, list[str] | str] | None = None,
    ) -> None:
        from synapse_saas.audit.service import AuditService

        AuditService(self.session).log(
            event_type,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            diff=diff,
        )


__all__ = ["KEY_PREFIX", "ApiKeyService"]
