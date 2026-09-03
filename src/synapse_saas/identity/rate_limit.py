"""Auth rate limiting.

Protects credential endpoints two ways: by client IP (network spray) and by
target identity (stuffing one account). Either counter tripping returns 429.

Errors deliberately mirror invalid-credential responses where feasible — but
429 is correct and informative here: the requester knows to back off, and
legitimate users with fat-fingered passwords are unlikely to hit 5/min.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from synapse_saas.core.config import get_settings
from synapse_saas.core.logging import get_logger
from synapse_saas.core.rate_limit import get_rate_limiter

logger = get_logger(__name__)

# Credential endpoints and the request field carrying the target identity.
AUTH_ROUTES: dict[str, str | None] = {
    "/v1/auth/login": "email",
    "/v1/auth/register": "email",
    "/v1/auth/forgot-password": "email",
    "/v1/auth/reset-password": None,  # token-based; IP limit only
}


def _client_ip(request: Request) -> str:
    # Behind a proxy/ingress the socket address is the proxy; honor the
    # forwarded chain only when the first hop is private (our own LB).
    forwarded = request.headers.get("x-forwarded-for", "")
    client = request.client.host if request.client else "unknown"
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return client


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        identity_field = AUTH_ROUTES.get(request.url.path)
        if request.url.path not in AUTH_ROUTES:
            response: Response = await call_next(request)
            return response
        # identity_field may legitimately be None (IP-only routes like reset-password)

        settings = get_settings()
        limiter = get_rate_limiter()
        ip = _client_ip(request)

        # IP bucket applies to every auth route
        try:
            await limiter.check(
                f"auth:ip:{ip}",
                limit=settings.auth_rate_limit_per_ip,
                window_seconds=settings.auth_rate_window_seconds,
            )
        except Exception as exc:  # RateLimitedError or Redis failure
            return _too_many(request, exc)

        # Identity bucket applies when the route carries a target account
        if identity_field and request.method == "POST":
            body_identity = await _peek_identity(request, identity_field)
            if body_identity:
                try:
                    await limiter.check(
                        f"auth:id:{body_identity}",
                        limit=settings.auth_rate_limit_per_identity,
                        window_seconds=settings.auth_rate_window_seconds,
                    )
                except Exception as exc:
                    return _too_many(request, exc)

        final: Response = await call_next(request)
        return final


async def _peek_identity(request: Request, field: str) -> str | None:
    """Read the identity field without consuming the body for the handler.

    Starlette caches `request._body` after the first read, so the downstream
    parser still sees the bytes.
    """
    import json

    try:
        body = await request.body()
        data = json.loads(body)
        value = data.get(field)
        return str(value).lower() if value else None
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return None


def _too_many(request: Request, exc: Exception) -> JSONResponse:
    from synapse_saas.core.errors import DomainError

    retry_after = getattr(exc, "extras", {}).get("retry_after_seconds", 60)
    logger.warning("auth_rate_limited", path=request.url.path, ip=_client_ip(request))
    with contextlib.suppress(Exception):  # metrics must never fail the 429 itself
        from synapse_saas.core import metrics

        metrics.AUTH_EVENTS.labels(event="rate_limited").inc()
    if isinstance(exc, DomainError):
        doc = exc.to_problem(instance=str(request.url.path))
    else:
        doc = {
            "type": "https://synapse-saas.dev/problems/rate_limited",
            "title": "rate limited",
            "status": 429,
            "detail": "Too many attempts; slow down and retry shortly.",
        }
    doc["retry_after_seconds"] = retry_after
    return JSONResponse(status_code=429, content=doc, headers={"Retry-After": str(retry_after)})
