"""The framework works when pip-installed, from any working directory (P4 / WS-J1):
the plan catalog and the migrations are package resources, not repo paths."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.pg


class TestFromAnotherDirectory:
    def test_catalog_loads_without_a_checkout(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.subscriptions.catalog import load_catalog

        monkeypatch.chdir(tmp_path)  # no config/ here
        monkeypatch.delenv("SYNAPSE_PLANS_FILE", raising=False)
        get_settings.cache_clear()
        try:
            catalog = load_catalog()
        finally:
            get_settings.cache_clear()
        assert {p.key for p in catalog.plans} >= {"free", "starter", "pro"}

    def test_alembic_config_resolves_the_packaged_scripts(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from alembic.script import ScriptDirectory

        from synapse_saas.cli import alembic_config

        monkeypatch.chdir(tmp_path)
        script = ScriptDirectory.from_config(alembic_config())
        heads = script.get_heads()
        assert len(heads) == 1
        assert "synapse_saas" in str(script.dir) and "migrations" in str(script.dir)

    def test_cli_migrate_runs_from_a_temp_cwd(self, tmp_path, migrated_db) -> None:
        env = {**os.environ, "SYNAPSE_REDIS_URL": ""}
        result = subprocess.run(
            [sys.executable, "-m", "synapse_saas.cli", "migrate"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert "Migrations applied." in result.stdout
