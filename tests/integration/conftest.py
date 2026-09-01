"""Integration test fixtures: compose Postgres, Alembic, per-test truncation.

Runs against the compose stack (`docker compose up -d postgres redis`).
Postgres-only — jsonb/partitions/RLS make sqlite a lie.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    import os

    return os.environ.get(
        "SYNAPSE_DATABASE_URL",
        "postgresql+asyncpg://synapse:synapse@localhost:5433/synapse",
    )


@pytest_asyncio.fixture(scope="session")
async def migrated_db() -> AsyncIterator[None]:
    """Apply migrations once per session (Alembic is sync — run it in a thread)."""
    import os
    from concurrent.futures import ThreadPoolExecutor

    os.environ["SYNAPSE_DATABASE_URL"] = _database_url()
    os.environ.setdefault("SYNAPSE_REDIS_URL", "")
    os.environ.setdefault("SYNAPSE_AUTO_SYNC_PLANS", "false")

    def _sync_migrate() -> None:
        from alembic import command
        from alembic.config import Config

        config = Config(str(REPO_ROOT / "database" / "alembic.ini"))
        config.set_main_option("script_location", str(REPO_ROOT / "database" / "migrations"))
        command.upgrade(config, "head")

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, _sync_migrate)
    yield


@pytest_asyncio.fixture
async def db_session(migrated_db) -> AsyncIterator[object]:
    """Fresh session with a rolled-back transaction — tests are isolated."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from synapse_saas.core.db import get_engine

    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def clean_db(migrated_db) -> AsyncIterator[None]:
    """Truncate all tables between tests (order-independent via CASCADE)."""
    from sqlalchemy import text

    from synapse_saas.core.db import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
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

    # The in-process TTL-dict cache outlives truncation — clear it or stale
    # permission/entitlement sets bleed across tests. Same for the rate limiter:
    # every test shares one client IP, so its bucket would trip suite-wide.
    from synapse_saas.core import cache as cache_module
    from synapse_saas.core import rate_limit as rl_module

    cache_module._ttl_backend = None
    rl_module.reset_rate_limiter()
    yield
    rl_module.reset_rate_limiter()


@pytest_asyncio.fixture
async def app(clean_db: None) -> AsyncIterator[object]:
    """FastAPI app with lifespan (seeds system roles + plans via sync)."""
    from synapse_saas.api.app import create_app
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.seeds import seed_system
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.sync import sync_plans

    # Seed before handing out the app
    factory = get_session_factory()
    async with factory() as session:
        await seed_system(session)
        await sync_plans(session, load_catalog(str(REPO_ROOT / "config" / "plans.yaml")))
        await session.commit()

    yield create_app()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def org_and_tokens(client: AsyncClient) -> dict[str, str]:
    """A registered user with one organization; returns tokens + ids."""
    register = await client.post(
        "/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "password12345",
            "display_name": "Owner",
        },
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
