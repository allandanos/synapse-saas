"""One shared outbound HTTP client per process.

Billing providers and webhook delivery reuse it (connection pooling, one
timeout policy); the API's lifespan and the worker's shutdown close it.
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT_SECONDS = 30

_shared: httpx.AsyncClient | None = None
_shared_loop: int | None = None


def get_http_client() -> httpx.AsyncClient:
    """The process-wide client. Rebuilt if the event loop it was created on is
    gone (one loop per test in the suite; production has exactly one loop)."""
    import asyncio

    global _shared, _shared_loop
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = None
    if _shared is None or _shared.is_closed or (loop_id is not None and _shared_loop != loop_id):
        _shared = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
        _shared_loop = loop_id
    return _shared


async def close_http_client() -> None:
    global _shared
    if _shared is not None and not _shared.is_closed:
        await _shared.aclose()
    _shared = None
