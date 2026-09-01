"""CLI tests in a subprocess — click's asyncio.run() needs a clean loop."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SYNAPSE_DATABASE_URL": os.environ.get(
            "SYNAPSE_DATABASE_URL",
            "postgresql+asyncpg://synapse:synapse@localhost:5433/synapse",
        ),
        "SYNAPSE_REDIS_URL": "",
        "SYNAPSE_AUTO_SYNC_PLANS": "false",
    }
    return subprocess.run(  # noqa: S603 — argv is our own test CLI, not user input
        [sys.executable, "-m", "synapse_saas.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )


class TestSeed:
    def test_seed_reports_counts(self) -> None:
        result = run_cli("seed")
        assert result.returncode == 0, result.stderr + result.stdout
        assert "16 permissions" in result.stdout
        assert "5 system roles" in result.stdout

    def test_seed_idempotent(self) -> None:
        first = run_cli("seed")
        assert first.returncode == 0
        again = run_cli("seed")
        assert again.returncode == 0
        assert "16 permissions" in again.stdout

    def test_seed_dev_creates_demo_org(self) -> None:
        result = run_cli("seed", "--dev")
        assert result.returncode == 0, result.stderr
        # Either freshly seeded or idempotently skipped — the org must exist
        assert "owner@acme.test" in result.stdout or "already seeded" in result.stdout

        from sqlalchemy import select

        from synapse_saas.core.db import dispose_engine, get_session_factory
        from synapse_saas.tenancy.models import Organization

        factory = get_session_factory()

        async def check() -> str | None:
            async with factory() as session:
                org = (
                    await session.execute(select(Organization).where(Organization.slug == "acme"))
                ).scalar_one_or_none()
                return org.name if org else None

        import asyncio

        name = asyncio.run(check())
        asyncio.run(dispose_engine())
        assert name == "Acme Corporation"


class TestPlansSync:
    def test_sync_reports_diff(self) -> None:
        result = run_cli("plans", "sync")
        assert result.returncode == 0, result.stderr
        assert "plans +" in result.stdout

    def test_sync_dry_run_for_stripe(self) -> None:
        result = run_cli("plans", "sync", "--provider", "stripe")
        assert result.returncode == 0, result.stderr
        assert "dry-run" in result.stdout
        assert "starter" in result.stdout

    def test_sync_unsupported_provider(self) -> None:
        result = run_cli("plans", "sync", "--provider", "manual", "--apply")
        assert result.returncode == 0
        assert "does not support plan sync" in result.stdout


class TestMigrate:
    def test_migrate_idempotent(self) -> None:
        first = run_cli("migrate")
        assert first.returncode == 0, first.stderr
        assert "Migrations applied" in first.stdout

        again = run_cli("migrate")
        assert again.returncode == 0


class TestHelp:
    def test_help_exits_cleanly(self) -> None:
        result = run_cli("--help")
        assert result.returncode == 0
        assert "seed" in result.stdout and "plans" in result.stdout
