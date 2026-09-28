"""A generated product migrates (framework branch + its own) against a real
database and its tables carry row-level security like the framework's."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.integration.conftest import owner_session_factory

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_generated_migrations_apply_and_roll_back(tmp_path: Path, migrated_db) -> None:
    from synapse_saas.scaffold import generate

    project = tmp_path / "smoke-app"
    generate("smoke-app", destination=project, framework_path=str(REPO_ROOT))

    env = {
        **os.environ,
        "SYNAPSE_REDIS_URL": "",
        "PYTHONPATH": str(project / "src"),
    }

    def alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — our own tooling
            [sys.executable, "-m", "smoke_app.migrate", *args],
            capture_output=True,
            text=True,
            cwd=project,
            env=env,
            timeout=180,
            check=False,
        )

    up = alembic("upgrade", "heads")
    assert up.returncode == 0, up.stderr + up.stdout
    async with owner_session_factory()() as session:
        exists = (
            await session.execute(text("SELECT to_regclass('public.smoke_app_projects') IS NOT NULL"))
        ).scalar_one()
        rls = (
            await session.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'smoke_app_projects'")
            )
        ).scalar_one()
        heads = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    assert exists and rls
    assert "0001_smoke_app_projects" in heads  # the product branch is recorded alongside the framework head

    down = alembic("downgrade", "smoke_app@base")
    assert down.returncode == 0, down.stderr + down.stdout
    async with owner_session_factory()() as session:
        gone = (
            await session.execute(text("SELECT to_regclass('public.smoke_app_projects') IS NULL"))
        ).scalar_one()
    assert gone
