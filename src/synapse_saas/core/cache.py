"""Version-counter cache with TTL-dict fallback.

Invalidation model: every cached body is stored under `key:v{version}` where
`version` comes from a separate counter key. Mutations bump the counter; readers
re-read the (tiny) counter first and only fetch the body on a version they
haven't seen. Without Redis, an in-process TTL dict keeps the framework running.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
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
    """get/set/expire around a version counter, with graceful degradation.

    Correctness rules (each one closed a real bug):
    - `set` writes under the version observed at *read* time (`get_versioned`),
      never a version re-read at write time: a bump between the read and the
      write must leave the new version empty, not fill it with the stale body.
    - `delete` is a bump. Resetting the counter to 0 would resurrect whatever
      body was cached under version 0.
    - Invalidation belongs AFTER commit: `defer_bump(session, …)` queues the bump
      on the session and `flush_deferred_bumps(session)` runs it once the
      transaction is durable (the request session does this automatically).
    """

    def __init__(self, namespace: str, *, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self.namespace = namespace
        self.ttl = ttl

    def _version_key(self, key: str) -> str:
        return f"{self.namespace}:ver:{key}"

    def _body_key(self, key: str, version: int) -> str:
        return f"{self.namespace}:v{version}:{key}"

    async def current_version(self, key: str) -> int:
        version_raw = await _backend().get(self._version_key(key))
        return int(version_raw) if version_raw else 0

    async def get_versioned(self, key: str) -> tuple[str | None, int]:
        """(body, version) — pass the version back to `set` after a miss."""
        backend = _backend()
        version = await self.current_version(key)
        return await backend.get(self._body_key(key, version)), version

    async def get(self, key: str, *, loader: None = None) -> str | None:
        body, _ = await self.get_versioned(key)
        return body

    async def set(self, key: str, value: str, *, version: int | None = None) -> None:
        """Store `value` under `version` (from `get_versioned`); a fresh read when omitted."""
        backend = _backend()
        if version is None:
            version = await self.current_version(key)
        await backend.set(self._body_key(key, version), value, ex=self.ttl)

    async def get_scoped(self, key: str, *scopes: str) -> tuple[str | None, str]:
        """A body that several counters can invalidate (e.g. a flag evaluation
        depends on the global, org and user scopes). Returns (body, token);
        pass the token back to `set_scoped` after a miss."""
        parts = [f"{scope}={await self.current_version(scope)}" for scope in scopes]
        token = ",".join(parts)
        return await _backend().get(self._scoped_key(key, token)), token

    async def set_scoped(self, key: str, value: str, token: str) -> None:
        await _backend().set(self._scoped_key(key, token), value, ex=self.ttl)

    def _scoped_key(self, key: str, token: str) -> str:
        return f"{self.namespace}:s[{token}]:{key}"

    async def bump(self, key: str) -> int:
        """Invalidate: increment the version counter. Next read misses."""
        backend = _backend()
        try:
            return await backend.incr(self._version_key(key))
        except Exception:
            logger.warning("cache_bump_failed", namespace=self.namespace, key=key)
            return -1

    async def delete(self, key: str) -> None:
        """Invalidate — implemented as a bump (see class docstring)."""
        await self.bump(key)


# ── Post-commit invalidation ─────────────────────────────────────────────────

_DEFERRED_KEY = "synapse_deferred_bumps"


def defer_bump(session: Any, cache: VersionedCache, key: str) -> None:
    """Queue `cache.bump(key)` to run after the session's transaction commits.

    Bumping inside the transaction lets a concurrent reader recompute from the
    pre-commit rows and cache them under the NEW version — stale for a full TTL
    after an upgrade. Deferring closes that window.
    """
    pending: list[tuple[VersionedCache, str]] = session.info.setdefault(_DEFERRED_KEY, [])
    if (cache, key) not in pending:
        pending.append((cache, key))


def discard_deferred_bumps(session: Any) -> None:
    session.info.pop(_DEFERRED_KEY, None)


async def flush_deferred_bumps(session: Any) -> int:
    """Run the bumps queued with `defer_bump`. Call after `commit()`."""
    pending: list[tuple[VersionedCache, str]] = session.info.pop(_DEFERRED_KEY, [])
    for cache, key in pending:
        await cache.bump(key)
    return len(pending)


_AFTER_COMMIT_KEY = "synapse_after_commit"


def defer_after_commit(session: Any, action: Callable[[], Awaitable[Any]], *, name: str = "") -> None:
    """Queue best-effort work for after the transaction commits (e.g. converging
    an external system to rows that are not visible until then). Failures are
    logged, never raised: the durable path (outbox) is the source of truth."""
    pending: list[tuple[str, Callable[[], Awaitable[Any]]]] = session.info.setdefault(_AFTER_COMMIT_KEY, [])
    pending.append((name or getattr(action, "__name__", "action"), action))


def discard_after_commit(session: Any) -> None:
    session.info.pop(_AFTER_COMMIT_KEY, None)


async def run_after_commit(session: Any) -> int:
    """Run the actions queued with `defer_after_commit`. Call after `commit()`."""
    pending: list[tuple[str, Callable[[], Awaitable[Any]]]] = session.info.pop(_AFTER_COMMIT_KEY, [])
    if pending:
        logger.debug("after_commit_actions", count=len(pending), actions=[name for name, _ in pending])
    for name, action in pending:
        try:
            await action()
        except Exception as exc:
            logger.warning("after_commit_action_failed", action=name, error=str(exc))
    return len(pending)


async def commit_and_flush_bumps(session: Any) -> None:
    """Jobs/CLI helper: commit, then run the deferred invalidations and actions."""
    await session.commit()
    await flush_deferred_bumps(session)
    await run_after_commit(session)
