"""Integration fixtures — see `synapse_saas.testing`.

Requires PostgreSQL (jsonb, partitions, RLS make sqlite a lie). Defaults to
the framework's scratch database on port 5434; override with
SYNAPSE_DATABASE_URL. Never point it at a database you care about: every test
TRUNCATEs every table.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://synapse:synapse@localhost:5434/synapse_test"


def database_url() -> str:
    """The app DSN under test (the RLS-subject role under `make test-rls`)."""
    return os.environ.get("SYNAPSE_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def owner_database_url() -> str:
    """Schema-owner DSN: migrations, TRUNCATE, and direct-DB helpers (bypasses RLS)."""
    return os.environ.get("SYNAPSE_WORKER_DATABASE_URL") or database_url()


# ── Database lifecycle ────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session")
async def migrated_db() -> AsyncIterator[None]:
    """Apply the packaged migrations once per session (Alembic is sync — run in a thread)."""
    from concurrent.futures import ThreadPoolExecutor

    os.environ["SYNAPSE_DATABASE_URL"] = database_url()
    os.environ.setdefault("SYNAPSE_REDIS_URL", "")
    os.environ.setdefault("SYNAPSE_AUTO_SYNC_PLANS", "false")

    def _sync_migrate() -> None:
        from alembic import command

        from synapse_saas.cli import alembic_config

        command.upgrade(alembic_config(), "head")

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, _sync_migrate)
    yield


_owner_engine: Any = None


def owner_engine() -> Any:
    """Engine bound to the owner DSN. Lazily built; disposed after every test."""
    global _owner_engine
    if _owner_engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine

        _owner_engine = create_async_engine(owner_database_url(), pool_pre_ping=True)
    return _owner_engine


def owner_session_factory() -> Any:
    """Session factory on the owner engine — for tests that poke the DB directly."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(owner_engine(), expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture(autouse=True)
async def _dispose_owner_engine() -> AsyncIterator[None]:
    """Every test runs on its own event loop; asyncpg connections are loop-bound.
    The app engine is disposed by the API lifespan per test; the owner engine here."""
    global _owner_engine
    yield
    if _owner_engine is not None:
        await _owner_engine.dispose()
        _owner_engine = None


@pytest_asyncio.fixture
async def db_session(migrated_db: None) -> AsyncIterator[Any]:
    """Fresh session with a rolled-back transaction — tests are isolated."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from synapse_saas.core.db import get_engine

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def clean_db(migrated_db: None) -> AsyncIterator[None]:
    """Truncate every table between tests (order-independent via CASCADE)."""
    from sqlalchemy import text

    async with owner_engine().begin() as conn:
        await conn.execute(
            text(
                """
                DO $$
                DECLARE r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public' AND tablename != 'alembic_version'
                    ) LOOP
                        EXECUTE format('TRUNCATE TABLE %I CASCADE', r.tablename);
                    END LOOP;
                END $$;
                """
            )
        )

    # In-process caches outlive truncation — clear them or stale permission /
    # entitlement sets bleed across tests. Same for the auth rate limiter:
    # every test shares one client IP, so its bucket would trip suite-wide.
    from synapse_saas.core import cache as cache_module
    from synapse_saas.core import rate_limit as rl_module

    cache_module._ttl_backend = None
    rl_module.reset_rate_limiter()
    yield
    rl_module.reset_rate_limiter()


# ── App + client ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app(clean_db: None) -> AsyncIterator[Any]:
    """The FastAPI app, with system roles + the packaged plan catalog seeded."""
    from synapse_saas.api.app import create_app
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.seeds import seed_system
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.sync import sync_plans

    async with get_session_factory()() as session:
        await seed_system(session)
        await sync_plans(session, load_catalog())
        await session.commit()

    yield create_app()


@pytest_asyncio.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """HTTP client against the booted app (lifespan runs: guards, auto-sync, self-tests)."""
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def org_and_tokens(client: AsyncClient) -> dict[str, str]:
    """A registered user with one organization; returns tokens + ids."""
    register = await client.post(
        "/v1/auth/register",
        json={"email": "owner@example.com", "password": "password12345", "display_name": "Owner"},
    )
    assert register.status_code == 201, register.text
    tokens = register.json()["tokens"]
    org = await client.post(
        "/v1/orgs",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"name": "Test Org", "slug": "test-org"},
    )
    assert org.status_code == 201, org.text
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "org_id": org.json()["id"],
    }


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    """Bearer + X-Org-Id for the org_and_tokens fixture (or any dict shaped like it)."""
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


# ── Branding ──────────────────────────────────────────────────────────────────


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@pytest.fixture
def custom_branding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    """Factory: `custom_branding(name="Acme", colors={"primary": "#ff0000"}, files={"x.png": b"…"})`.

    Writes the packaged kit with the overrides deep-merged into branding.yaml
    (a top-level `None` deletes the key) plus any extra `files`, points
    SYNAPSE_BRANDING_FILE at it and clears the settings + branding caches.
    Returns the branding.yaml path; caches are cleared again on teardown.
    """
    import yaml

    from synapse_saas.branding.loader import reset_branding, write_starter_kit
    from synapse_saas.core.config import get_settings

    counter = iter(range(1_000_000))

    def make(*, files: dict[str, bytes] | None = None, **overrides: Any) -> Path:
        kit = tmp_path / f"branding-{next(counter)}"
        write_starter_kit(kit)
        path = kit / "branding.yaml"
        raw = _deep_merge(yaml.safe_load(path.read_text(encoding="utf-8")), overrides)
        raw = {key: value for key, value in raw.items() if value is not None}
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        for name, content in (files or {}).items():
            (kit / name).write_bytes(content)
        monkeypatch.setenv("SYNAPSE_BRANDING_FILE", str(path))
        get_settings.cache_clear()
        reset_branding()
        return path

    yield make
    get_settings.cache_clear()
    reset_branding()


# ── Platform operator helpers ─────────────────────────────────────────────────
# Grants and money movements are operator actions (ADR 0008). Tests that use
# them as *setup* call these; tests proving the tenant CANNOT call the routes.

PLATFORM_ADMIN_EMAIL = "operator@platform.example.com"
PLATFORM_ADMIN_PASSWORD = "operator-password-12345"


async def platform_admin_headers(client: AsyncClient) -> dict[str, str]:
    """Register (once per DB state) and promote a platform operator; return auth headers."""
    from sqlalchemy import select

    from synapse_saas.identity.models import User

    reg = await client.post(
        "/v1/auth/register",
        json={"email": PLATFORM_ADMIN_EMAIL, "password": PLATFORM_ADMIN_PASSWORD, "display_name": "Operator"},
    )
    if reg.status_code == 201:
        async with owner_session_factory()() as session:
            user = (
                await session.execute(select(User).where(User.email == PLATFORM_ADMIN_EMAIL))
            ).scalar_one()
            user.is_platform_admin = True
            await session.commit()
    login = await client.post(
        "/v1/auth/login", json={"email": PLATFORM_ADMIN_EMAIL, "password": PLATFORM_ADMIN_PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


async def grant_as_platform(client: AsyncClient, org_id: str, body: dict[str, object]) -> Any:
    headers = await platform_admin_headers(client)
    return await client.post(f"/v1/admin/orgs/{org_id}/entitlements/grants", headers=headers, json=body)


async def pay_as_platform(client: AsyncClient, invoice_id: str, body: dict[str, object]) -> Any:
    headers = await platform_admin_headers(client)
    return await client.post(f"/v1/billing/admin/invoices/{invoice_id}/pay", headers=headers, json=body)


async def void_as_platform(client: AsyncClient, invoice_id: str) -> Any:
    headers = await platform_admin_headers(client)
    return await client.post(f"/v1/billing/admin/invoices/{invoice_id}/void", headers=headers)


__all__ = [
    "DEFAULT_TEST_DATABASE_URL",
    "PLATFORM_ADMIN_EMAIL",
    "PLATFORM_ADMIN_PASSWORD",
    "app",
    "clean_db",
    "client",
    "custom_branding",
    "database_url",
    "db_session",
    "grant_as_platform",
    "migrated_db",
    "org_and_tokens",
    "org_headers",
    "owner_database_url",
    "owner_engine",
    "owner_session_factory",
    "pay_as_platform",
    "platform_admin_headers",
    "void_as_platform",
]
