"""Rate limiter unit tests — local fallback semantics."""

from __future__ import annotations

import pytest

from synapse_saas.core.errors import RateLimitedError
from synapse_saas.core.rate_limit import RateLimiter


class TestLocalFallback:
    async def test_allows_up_to_limit(self) -> None:
        limiter = RateLimiter(None)
        for _ in range(5):
            await limiter.check("k", limit=5, window_seconds=60)

    async def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(None)
        for _ in range(3):
            await limiter.check("k", limit=3, window_seconds=60)
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check("k", limit=3, window_seconds=60)
        assert exc_info.value.status == 429
        assert exc_info.value.extras["retry_after_seconds"] >= 1

    async def test_independent_keys(self) -> None:
        limiter = RateLimiter(None)
        for _ in range(3):
            await limiter.check("a", limit=3, window_seconds=60)
        await limiter.check("b", limit=3, window_seconds=60)  # unaffected

    async def test_problem_document_shape(self) -> None:
        limiter = RateLimiter(None)
        for _ in range(2):
            await limiter.check("k", limit=2, window_seconds=60)
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check("k", limit=2, window_seconds=60)
        doc = exc_info.value.to_problem()
        assert doc["status"] == 429
        assert doc["type"].endswith("/rate_limited")
        assert doc["limit"] == 2
        assert doc["retry_after_seconds"] >= 1


class TestRedisBackend:
    async def test_redis_pipeline_blocks(self) -> None:
        """Redis path: INCR returns counts; over-limit raises."""
        from unittest.mock import AsyncMock, MagicMock

        redis = MagicMock()
        pipe = MagicMock()
        pipe.incr = MagicMock()
        pipe.ttl = MagicMock()
        pipe.execute = AsyncMock(return_value=[6, 42])
        redis.pipeline.return_value = pipe

        limiter = RateLimiter(redis)  # type: ignore[arg-type]
        with pytest.raises(RateLimitedError) as exc_info:
            await limiter.check("k", limit=5, window_seconds=60)
        assert exc_info.value.extras["retry_after_seconds"] == 42

    async def test_redis_sets_expiry_on_new_key(self) -> None:
        """A brand-new key with TTL -1 (no expiry) gets one set."""
        from unittest.mock import AsyncMock, MagicMock

        redis = MagicMock()
        pipe = MagicMock()
        pipe.incr = MagicMock()
        pipe.ttl = MagicMock()
        pipe.execute = AsyncMock(return_value=[1, -1])  # first hit, no TTL yet
        redis.pipeline.return_value = pipe
        redis.expire = AsyncMock()

        limiter = RateLimiter(redis)  # type: ignore[arg-type]
        await limiter.check("k", limit=5, window_seconds=60)
        redis.expire.assert_awaited_once()
