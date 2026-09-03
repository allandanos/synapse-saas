"""Feature flag resolution.

Pure bucketing + DB lookup with a version-counter cache. Deterministic: the
same (flag, org/user) always resolves the same way within and across requests,
because bucketing hashes stable identifiers — never randomness at read time.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core.cache import VersionedCache
from synapse_saas.core.errors import FeatureFlagNotFoundError
from synapse_saas.core.logging import get_logger
from synapse_saas.feature_flags.models import FeatureFlag, FeatureFlagOverride

logger = get_logger(__name__)

_cache = VersionedCache("fflags", ttl=30)

BUCKETS = 10_000


def bucket_of(flag_key: str, identifier: str) -> int:
    """Deterministic bucket 0..BUCKETS-1 from (flag_key, identifier)."""
    import hashlib

    digest = hashlib.sha256(f"{flag_key}:{identifier}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % BUCKETS


def in_rollout(flag_key: str, identifier: str, percentage: int) -> bool:
    """True when `identifier` falls inside the first `percentage`% of buckets."""
    return bucket_of(flag_key, identifier) < (BUCKETS * percentage) // 100


class FeatureFlagService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Resolution ──────────────────────────────────────────────────────────────

    async def is_enabled(
        self,
        flag_key: str,
        *,
        organization_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> bool:
        """Resolve flag → user override → org override → global (rollout-aware)."""
        flag = await self._flag(flag_key)
        if flag is None:
            return False  # unknown flags are off — new code paths dark by default

        # Most specific override wins
        if user_id is not None:
            override = await self._override(flag_key, user_id=user_id)
            if override is not None:
                return override.enabled
        if organization_id is not None:
            override = await self._override(flag_key, organization_id=organization_id)
            if override is not None:
                return override.enabled

        # Global default, possibly gated by a deterministic rollout
        if flag.rollout_percentage is not None:
            identifier = str(user_id or organization_id or "anonymous")
            return in_rollout(flag_key, identifier, flag.rollout_percentage)
        return flag.enabled

    # ── Management (platform-admin surface) ─────────────────────────────────────

    async def create_flag(
        self,
        *,
        key: str,
        name: str,
        description: str | None = None,
        enabled: bool = False,
        rollout_percentage: int | None = None,
    ) -> FeatureFlag:
        existing = await self._flag(key)
        if existing is not None:
            raise FeatureFlagNotFoundError(f"Flag {key!r} already exists")  # 404-class misuse
        flag = FeatureFlag(
            key=key,
            name=name,
            description=description,
            enabled=enabled,
            rollout_percentage=rollout_percentage,
        )
        self.session.add(flag)
        await self.session.flush()
        await _cache.bump("all")
        return flag

    async def update_flag(
        self,
        key: str,
        *,
        enabled: bool | None = None,
        rollout_percentage: int | None = None,
    ) -> FeatureFlag:
        flag = await self._flag(key)
        if flag is None or flag.archived_at is not None:
            raise FeatureFlagNotFoundError(f"Flag {key!r} not found")
        if enabled is not None:
            flag.enabled = enabled
        if rollout_percentage is not None:
            flag.rollout_percentage = rollout_percentage
        await self.session.flush()
        await _cache.bump("all")
        return flag

    async def set_override(
        self,
        flag_key: str,
        *,
        organization_id: UUID | None = None,
        user_id: UUID | None = None,
        enabled: bool,
        note: str | None = None,
    ) -> FeatureFlagOverride:
        flag = await self._flag(flag_key)
        if flag is None or flag.archived_at is not None:
            raise FeatureFlagNotFoundError(f"Flag {flag_key!r} not found")
        if organization_id is None and user_id is None:
            raise FeatureFlagNotFoundError("Override requires an organization_id or user_id")

        existing = await self._override(flag_key, organization_id=organization_id, user_id=user_id)
        if existing is not None:
            existing.enabled = enabled
            existing.note = note
            await self.session.flush()
            await self._bump_scope(organization_id, user_id)
            return existing

        override = FeatureFlagOverride(
            flag_key=flag_key,
            organization_id=organization_id,
            user_id=user_id,
            enabled=enabled,
            note=note,
        )
        self.session.add(override)
        await self.session.flush()
        await self._bump_scope(organization_id, user_id)
        return override

    async def delete_override(self, override_id: UUID) -> None:
        override = await self.session.get(FeatureFlagOverride, override_id)
        if override is None:
            raise FeatureFlagNotFoundError("Override not found")
        await self.session.delete(override)
        await self.session.flush()
        await self._bump_scope(override.organization_id, override.user_id)

    async def list_flags(self) -> list[FeatureFlag]:
        result = await self.session.execute(
            select(FeatureFlag).where(FeatureFlag.archived_at.is_(None)).order_by(FeatureFlag.key)
        )
        return list(result.scalars().all())

    async def list_overrides(self, flag_key: str) -> list[FeatureFlagOverride]:
        result = await self.session.execute(
            select(FeatureFlagOverride)
            .where(FeatureFlagOverride.flag_key == flag_key)
            .order_by(FeatureFlagOverride.created_at.desc())
        )
        return list(result.scalars().all())

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _flag(self, key: str) -> FeatureFlag | None:
        return (
            await self.session.execute(
                select(FeatureFlag).where(FeatureFlag.key == key, FeatureFlag.archived_at.is_(None))
            )
        ).scalar_one_or_none()

    async def _override(
        self,
        flag_key: str,
        *,
        organization_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> FeatureFlagOverride | None:
        stmt = select(FeatureFlagOverride).where(FeatureFlagOverride.flag_key == flag_key)
        if user_id is not None:
            stmt = stmt.where(FeatureFlagOverride.user_id == user_id)
        elif organization_id is not None:
            stmt = stmt.where(
                FeatureFlagOverride.organization_id == organization_id,
                FeatureFlagOverride.user_id.is_(None),
            )
        else:
            return None
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _bump_scope(self, organization_id: UUID | None, user_id: UUID | None) -> None:
        if organization_id is not None:
            await _cache.bump(f"org:{organization_id}")
        if user_id is not None:
            await _cache.bump(f"user:{user_id}")
