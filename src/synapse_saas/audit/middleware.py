"""Request middleware: request-id propagation, structlog binding, security headers."""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from synapse_saas.core import context
from synapse_saas.core.logging import bind_request_context, clear_request_context

REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates a request id and binds log context for the whole request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or f"req_{uuid.uuid4().hex[:16]}"
        token = context.set_request_id(request_id)
        start = time.perf_counter()
        span_cm = _request_span(request)
        span_cm.__enter__()  # the span is CURRENT: handlers' spans nest under it, logs carry trace_id
        bind_request_context()  # request_id + trace_id on every log line from here on;
        # tenant/user are rebound by the auth dependencies once they resolve.
        try:
            response = await call_next(request)
        finally:
            context.reset_request_id(token)
            span_cm.__exit__(None, None, None)
            clear_request_context()  # never leak ids into the next request on this task

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        try:
            from synapse_saas.core import metrics
            from synapse_saas.core.config import get_settings

            if get_settings().metrics_enabled:
                metrics.record_http(
                    request.method,
                    self._route_template(request),
                    response.status_code,
                    duration_ms / 1000,
                )
        except Exception:  # metrics must never fail a request
            from synapse_saas.core.logging import get_logger

            get_logger(__name__).debug("metrics_record_failed")

        return response

    @staticmethod
    def _route_template(request: Request) -> str:
        """Path template when matched (bounded), else 'unmatched'."""
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            return str(route.path)
        return "unmatched"


def _request_span(request: Request) -> _SpanGuard:
    """Server span per request; inert until an exporter is configured."""
    return _SpanGuard(request)


class _SpanGuard:
    """Starts a span on enter and makes it CURRENT (so `current_trace_id()` and
    child spans see it); ends it on exit. Tracing failures are absorbed — the
    request path is identical whether or not spans are being recorded."""

    def __init__(self, request: Request) -> None:
        self._request = request
        self._cm: Any = None

    def __enter__(self) -> _SpanGuard:
        with contextlib.suppress(Exception):
            from synapse_saas.core.tracing import get_tracer

            self._cm = get_tracer("synapse.http").start_as_current_span(
                f"{self._request.method} {self._request.url.path}"
            )
            self._cm.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        with contextlib.suppress(Exception):
            if self._cm is not None:
                self._cm.__exit__(None, None, None)
        self._cm = None
