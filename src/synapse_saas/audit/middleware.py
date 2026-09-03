"""Request middleware: request-id propagation, structlog binding, security headers."""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from synapse_saas.core import context
from synapse_saas.core.logging import bind_request_context

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
        span_cm.__enter__()
        try:
            response = await call_next(request)
        finally:
            context.reset_request_id(token)
            span_cm.__exit__(None, None, None)

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        bind_request_context()

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
    """Starts a span on enter, ends it on exit. Tracing failures are absorbed —
    the request path is identical whether or not spans are being recorded."""

    def __init__(self, request: Request) -> None:
        self._request = request
        self._span: object | None = None

    def __enter__(self) -> _SpanGuard:
        with contextlib.suppress(Exception):
            from synapse_saas.core.tracing import get_tracer

            self._span = get_tracer("synapse.http").start_span(
                f"{self._request.method} {self._request.url.path}"
            )
        return self

    def __exit__(self, *exc: object) -> None:
        with contextlib.suppress(Exception):
            if self._span is not None:
                self._span.end()  # type: ignore[attr-defined]
        self._span = None
