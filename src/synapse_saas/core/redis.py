"""Redis client factory.

`get_redis()` returns None when no URL is configured — every consumer must
tolerate that (framework runs lean without Redis; caches degrade to TTL dicts,
jobs fall back to in-process scheduling).
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from synapse_saas.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis | None:
    """Return the shared Redis client, or None when not configured/unavailable."""
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.redis_url:
        return None
    _client = from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
