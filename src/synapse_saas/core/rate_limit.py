"""Rate limiting: Redis-backed fixed window with in-process fallback.

Two keys protect every attempt: the client IP (network-level abuse) and the
target identity (credential stuffing against one account). Either tripping
blocks the request with 429.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synapse_saas.core.errors import RateLimitedError
from synapse_saas.core.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


class RateLimiter:
    """Fixed-window counter. Redis INCR+EXPIRE when available; dict otherwise.

    The fallback is per-process — acceptable degradation for single-instance
    dev; production runs Redis.
    """

    def __init__(self, redis_client: Redis | None, *, prefix: str = "rl") -> None:
        self._redis: Redis | None = redis_client
        self._prefix = prefix
        self._local: dict[str, int] = {}
        self._local_windows: dict[str, int] = {}

    async def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        """Raise RateLimitedError when `key` exceeds `limit` in the window."""
        if self._redis is not None:
            await self._check_redis(key, limit, window_seconds)
        else:
            self._check_local(key, limit, window_seconds)

    async def _check_redis(self, key: str, limit: int, window_seconds: int) -> None:
        assert self._redis is not None  # caller checked _redis is not None
        full = f"{self._prefix}:{key}"
        pipe = self._redis.pipeline()
        pipe.incr(full)
        pipe.ttl(full)
        count, ttl = await pipe.execute()

        if ttl == -1:
            # INCR created the key without an expiry (first hit raced) — set it
            await self._redis.expire(full, window_seconds)
            ttl = window_seconds

        if int(count) > limit:
            raise RateLimitedError(
                "Too many attempts; slow down and retry shortly",
                extras={"retry_after_seconds": max(int(ttl), 1), "limit": limit},
            )

    def _check_local(self, key: str, limit: int, window_seconds: int) -> None:
        import time

        now = int(time.time())
        window = now // window_seconds

        if self._local_windows.get(key) != window:
            self._local.pop(key, None)
            self._local_windows[key] = window

        count = self._local.get(key, 0) + 1
        self._local[key] = count

        if count > limit:
            retry_after = window_seconds - (now % window_seconds)
            raise RateLimitedError(
                "Too many attempts; slow down and retry shortly",
                extras={"retry_after_seconds": max(retry_after, 1), "limit": limit},
            )


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        from synapse_saas.core.redis import get_redis

        _limiter = RateLimiter(get_redis())
    return _limiter


def reset_rate_limiter() -> None:
    """Test hook: drop the cached limiter (settings may have changed Redis)."""
    global _limiter
    _limiter = None


__all__ = ["RateLimiter", "get_rate_limiter", "reset_rate_limiter"]
