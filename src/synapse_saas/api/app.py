"""Application factory."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from synapse_saas.api.v1 import api_v1
from synapse_saas.audit.middleware import RequestContextMiddleware
from synapse_saas.core import context
from synapse_saas.core.commit_before_send import CommitBeforeSendMiddleware
from synapse_saas.core.config import get_settings
from synapse_saas.core.db import assert_role_matches_isolation, dispose_engine, get_session_factory
from synapse_saas.core.errors import DomainError, HttpError, MethodNotAllowedError, NotFoundError
from synapse_saas.core.logging import configure_logging, get_logger
from synapse_saas.core.redis import close_redis
from synapse_saas.identity.rate_limit import AuthRateLimitMiddleware

logger = get_logger(__name__)

# The framework release (pyproject `version`); bumped with it, asserted by a unit test.
FRAMEWORK_VERSION = "0.1.0"
DEFAULT_API_DESCRIPTION = "Multi-tenant SaaS framework: tenancy, plans, entitlements, usage, billing."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()
    from synapse_saas.core.tracing import configure_tracing

    configure_tracing()

    # RLS posture must match the connected role, or the deployment is either
    # unprotected (bypassing role) or locked out (subject role, RLS off).
    try:
        await assert_role_matches_isolation()
    except Exception as exc:
        logger.exception("db_role_isolation_check_failed", error=str(exc))
        if settings.is_production or "RoleIsolationMismatch" in type(exc).__name__:
            raise

    if settings.auto_sync_plans:
        try:
            from synapse_saas.subscriptions.catalog import load_catalog
            from synapse_saas.subscriptions.sync import sync_plans

            catalog = load_catalog()
            async with get_session_factory()() as session:
                result = await sync_plans(session, catalog)
                await session.commit()
            logger.info("plans_auto_synced", **result.summary())
        except Exception as exc:
            logger.exception("plans_auto_sync_failed", error=str(exc))
            if settings.is_production:
                raise

    # Refuse to boot if the commit-before-send guarantee silently stopped working
    # (it depends on a FastAPI-private scope key — see core/commit_before_send.py)
    from synapse_saas.core.commit_before_send import assert_effective

    await assert_effective(app)

    yield
    await close_redis()
    await dispose_engine()
    from synapse_saas.core.http import close_http_client

    await close_http_client()


def _install_problem_handlers(app: FastAPI) -> None:
    """Every error leaves as an RFC 7807 problem document (contract v1)."""

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_problem(
                instance=str(request.url.path),
                request_id=context.current_request_id() or request.headers.get("X-Request-Id") or _trace_id(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Unknown routes and wrong methods are problem documents too (contract v1:
        every error body is RFC 7807), not Starlette's bare `{"detail": ...}`."""
        detail = str(exc.detail) if exc.detail else ""
        error: DomainError
        if exc.status_code == 404:
            error = NotFoundError(detail or "Not found")
        elif exc.status_code == 405:
            error = MethodNotAllowedError(detail or "Method not allowed")
        else:
            error = HttpError(detail or "Request rejected")
            error.status = exc.status_code
        return JSONResponse(
            status_code=exc.status_code,
            headers=dict(exc.headers or {}),
            content=error.to_problem(
                instance=str(request.url.path),
                request_id=context.current_request_id() or request.headers.get("X-Request-Id") or _trace_id(),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Request-parsing failures are problem documents too (contract v1: every
        error body is RFC 7807). The parser's per-field list rides in `errors`."""
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        fields = ", ".join(".".join(str(part) for part in e["loc"][1:]) or "body" for e in errors[:3])
        return JSONResponse(
            status_code=422,
            content={
                "type": "https://synapse-saas.dev/problems/validation_failed",
                "title": "validation failed",
                "status": 422,
                "detail": f"Invalid request: {fields}",
                "instance": str(request.url.path),
                "request_id": context.current_request_id()
                or request.headers.get("X-Request-Id")
                or _trace_id(),
                "errors": errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            error=str(exc),
            path=str(request.url.path),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "type": "https://synapse-saas.dev/problems/internal_error",
                "title": "internal error",
                "status": 500,
                "detail": "An unexpected error occurred.",
                "request_id": context.current_request_id() or request.headers.get("X-Request-Id"),
            },
        )


def create_app() -> FastAPI:
    from synapse_saas.branding.loader import get_branding

    settings = get_settings()
    # Fail fast: a broken branding kit stops the API before it binds a port.
    brand = get_branding()
    app = FastAPI(
        title=f"{brand.name} API",
        version=FRAMEWORK_VERSION,
        description=brand.tagline or DEFAULT_API_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "Retry-After", "Content-Disposition", "X-Total-Count"],
    )
    app.add_middleware(AuthRateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    # Innermost: session commits land before the first response byte —
    # a follow-up request on the same connection can never read pre-commit
    # state (see core/commit_before_send.py).
    app.add_middleware(CommitBeforeSendMiddleware)

    _install_problem_handlers(app)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Readiness: 200 when every dependency answers, **503** otherwise —
        so a Kubernetes readiness probe actually pulls a broken pod."""
        checks: dict[str, str] = {}
        try:
            async with get_session_factory()() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc}"
        from synapse_saas.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is None:
            checks["redis"] = "not_configured"
        else:
            try:
                await redis_client.ping()
                checks["redis"] = "ok"
            except Exception as exc:
                checks["redis"] = f"error: {exc}"
        overall = "ok" if all(v in {"ok", "not_configured"} for v in checks.values()) else "error"
        return JSONResponse(
            status_code=200 if overall == "ok" else 503, content={"status": overall, "checks": checks}
        )

    @app.get("/metrics", tags=["health"], include_in_schema=False)
    async def prometheus_metrics() -> Response:
        from prometheus_client import generate_latest

        from synapse_saas.core import metrics

        if not settings.metrics_enabled:
            return Response(status_code=404)
        with contextlib.suppress(Exception):  # pool snapshot is best-effort
            metrics.record_pool()
        return Response(content=generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/meta", tags=["health"])
    async def meta() -> dict[str, str]:
        return {
            "framework": "synapse-saas",
            "product": brand.name,
            "version": FRAMEWORK_VERSION,
            "billing_provider": settings.billing_provider,
            "identity_provider": settings.identity_provider,
            "tenant_isolation": settings.tenant_isolation,
        }

    app.include_router(api_v1)
    return app


def _trace_id() -> str | None:
    from synapse_saas.core.tracing import current_trace_id

    return current_trace_id()
