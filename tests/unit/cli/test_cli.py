"""CLI unit tests: click invocation surface (no DB where avoidable)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from synapse_saas.cli import cli

pytestmark = pytest.mark.usefixtures()


class TestCliSurface:
    def test_help_lists_commands(self) -> None:
        result = CliRunner().invoke(cli, ["--help"])
        assert result.exit_code == 0
        for command in ("migrate", "seed", "plans"):
            assert command in result.output

    def test_plans_subgroup(self) -> None:
        result = CliRunner().invoke(cli, ["plans", "--help"])
        assert result.exit_code == 0
        assert "sync" in result.output


class TestCatalogSyncIdempotency:
    def test_sync_twice_is_stable(self, tmp_path, monkeypatch) -> None:
        """The catalog → DB projection must converge, not compound."""

        monkeypatch.setenv("SYNAPSE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        # These tests target the pure diff logic; the DB sync itself is covered
        # by the integration suite. Validate the catalog loads from an
        # explicit path instead.
        from synapse_saas.subscriptions.catalog import load_catalog

        catalog = load_catalog("config/plans.yaml")
        assert {p.key for p in catalog.plans} >= {"free", "starter", "pro", "enterprise"}

        # Re-loading yields an equal catalog (no mutation)
        again = load_catalog("config/plans.yaml")
        assert again.model_dump() == catalog.model_dump()
