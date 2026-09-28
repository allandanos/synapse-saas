"""`synapse-cli jobs run-once` (P4 / WS-F F6): the scheduler-driven shape of the worker."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.pg

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SYNAPSE_REDIS_URL": ""}
    return subprocess.run(  # noqa: S603 — argv is our own CLI, not user input
        [sys.executable, "-m", "synapse_saas.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )


class TestJobsRunOnce:
    def test_all_runs_every_job_once(self, migrated_db) -> None:
        result = _run("jobs", "run-once", "--all")
        assert result.returncode == 0, result.stderr + result.stdout
        lines = [line for line in result.stdout.splitlines() if ":" in line]
        names = {line.split(":")[0] for line in lines}
        assert names == {
            "dispatch_outbox",
            "deliver_webhooks",
            "rollup_usage",
            "expire_entitlements",
            "advance_recurring_billing",
            "ensure_partitions",
            "purge_expired",
        }
        assert not any("error" in line for line in lines), result.stdout

    def test_named_subset(self, migrated_db) -> None:
        result = _run("jobs", "run-once", "ensure_partitions", "purge_expired")
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[0].startswith("ensure_partitions:")

    def test_unknown_job_is_a_usage_error(self) -> None:
        result = _run("jobs", "run-once", "make_coffee")
        assert result.returncode != 0
        assert "Unknown job" in result.stderr

    def test_nothing_selected_is_a_usage_error(self) -> None:
        result = _run("jobs", "run-once")
        assert result.returncode != 0
        assert "--all" in result.stderr
