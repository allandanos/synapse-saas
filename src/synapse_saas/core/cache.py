"""Version-counter cache with TTL-dict fallback.

Invalidation model: every cached body is stored under `key:v{version}` where
`version` comes from a separate counter key. Mutations bump the counter; readers
re-read the (tiny) counter first and only fetch the body on a version they
haven't seen. Without Redis, an in-process TTL dict keeps the framework running.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from synapse_saas.core.logging import get_logger
from synapse_saas.core.redis import get_redis

logger = get_logger(__name__)

DEFAULT_TTL_SECONDS = 60
_VERSION_TTL_SECONDS = 3600


class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ex: int) -> Any: ...
    async def delete(self, *keys: str) -> Any: ...
    async def incr(self, key: str) -> int: ...


class TTLDictBackend:
    """In-process fallback (single worker). Good enough to run lean; not shared."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < time.monotonic():
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self._store[key] = (time.monotonic() + ex, value)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        current = await self.get(key)
        value = (int(current) if current else 0) + 1
        self._store[key] = (time.monotonic() + _VERSION_TTL_SECONDS, str(value))
        return value


_ttl_backend: TTLDictBackend | None = None


def _backend() -> CacheBackend:
    global _ttl_backend
    redis_client = get_redis()
    if redis_client is not None:
        return redis_client  # type: ignore[return-value]
    if _ttl_backend is None:
        _ttl_backend = TTLDictBackend()
    return _ttl_backend


class VersionedCache:
    """get/set/expire around a version counter, with graceful degradation."""

    def __init__(self, namespace: str, *, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self.namespace = namespace
        self.ttl = ttl

    def _version_key(self, key: str) -> str:
        return f"{self.namespace}:ver:{key}"

    def _body_key(self, key: str, version: int) -> str:
        return f"{self.namespace}:v{version}:{key}"

    async def get(self, key: str, *, loader: None = None) -> str | None:
        backend = _backend()
        version_raw = await backend.get(self._version_key(key))
        version = int(version_raw) if version_raw else 0
        return await backend.get(self._body_key(key, version))

    async def set(self, key: str, value: str) -> None:
        backend = _backend()
        version_raw = await backend.get(self._version_key(key))
        version = int(version_raw) if version_raw else 0
        await backend.set(self._body_key(key, version), value, ex=self.ttl)

    async def bump(self, key: str) -> int:
        """Invalidate: increment the version counter. Next read misses."""
        backend = _backend()
        try:
            return await backend.incr(self._version_key(key))
        except Exception:
            logger.warning("cache_bump_failed", namespace=self.namespace, key=key)
            return -1

    async def delete(self, key: str) -> None:
        await _backend().delete(self._version_key(key))
