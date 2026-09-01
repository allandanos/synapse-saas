"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from synapse_saas.api.v1 import api_v1
from synapse_saas.audit.middleware import RequestContextMiddleware
from synapse_saas.core.config import get_settings
from synapse_saas.core.db import dispose_engine, get_session_factory
from synapse_saas.core.errors import DomainError
from synapse_saas.core.logging import configure_logging, get_logger
from synapse_saas.core.redis import close_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging()

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

    yield
    await close_redis()
    await dispose_engine()
    from synapse_saas.billing.registry import close_http_client

    await close_http_client()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Synapse SaaS Framework",
        version="0.1.0",
        description="Multi-tenant SaaS framework: tenancy, plans, entitlements, usage, billing.",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_problem(
                instance=str(request.url.path),
                request_id=request.headers.get("X-Request-Id"),
            ),
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
                "request_id": request.headers.get("X-Request-Id"),
            },
        )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, object]:
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
        return {"status": overall, "checks": checks}

    @app.get("/v1/meta", tags=["health"])
    async def meta() -> dict[str, str]:
        return {
            "framework": "synapse-saas",
            "version": "0.1.0",
            "billing_provider": settings.billing_provider,
            "identity_provider": settings.identity_provider,
            "tenant_isolation": settings.tenant_isolation,
        }

    app.include_router(api_v1)
    return app
