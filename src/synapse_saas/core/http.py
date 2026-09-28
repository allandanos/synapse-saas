"""One shared outbound HTTP client per process.

Billing providers and webhook delivery reuse it (connection pooling, one
timeout policy); the API's lifespan and the worker's shutdown close it.
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT_SECONDS = 30

_shared: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _shared
    if _shared is None or _shared.is_closed:
        _shared = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
    return _shared


async def close_http_client() -> None:
    global _shared
    if _shared is not None and not _shared.is_closed:
        await _shared.aclose()
    _shared = None
