"""synapse-cli branding init|validate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from click.testing import CliRunner

from synapse_saas.cli import cli


def test_init_then_validate(tmp_path: Path) -> None:
    runner = CliRunner()
    kit = tmp_path / "branding"
    init = runner.invoke(cli, ["branding", "init", "--dir", str(kit)])
    assert init.exit_code == 0, init.output
    assert sorted(p.name for p in kit.iterdir()) == ["branding.yaml", "favicon.svg", "logo.svg"]

    validate = runner.invoke(cli, ["branding", "validate", "--file", str(kit / "branding.yaml")])
    assert validate.exit_code == 0, validate.output
    assert "ok: 'Synapse'" in validate.output


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(cli, ["branding", "init", "--dir", str(tmp_path)]).exit_code == 0
    again = runner.invoke(cli, ["branding", "init", "--dir", str(tmp_path)])
    assert again.exit_code == 1
    assert "--force" in again.output
    assert runner.invoke(cli, ["branding", "init", "--dir", str(tmp_path), "--force"]).exit_code == 0


def test_validate_lists_every_error_and_exits_1(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["branding", "init", "--dir", str(tmp_path)])
    path = tmp_path / "branding.yaml"
    path.write_text(path.read_text().replace('primary: "#18181b"', "primary: black"))
    (tmp_path / "logo.svg").unlink()

    bad_schema = runner.invoke(cli, ["branding", "validate", "--file", str(path)])
    assert bad_schema.exit_code == 1
    assert "colors.primary" in bad_schema.output

    path.write_text(path.read_text().replace("primary: black", 'primary: "#000000"'))
    missing = runner.invoke(cli, ["branding", "validate", "--file", str(path)])
    assert missing.exit_code == 1
    assert "logo.svg" in missing.output


def _kit_with_tour(runner: CliRunner, tmp_path: Path, tour: dict[str, Any]) -> Path:
    """The default kit (assets included) with its `tour` key replaced by TOUR."""
    runner.invoke(cli, ["branding", "init", "--dir", str(tmp_path)])
    path = tmp_path / "branding.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({**raw, "tour": tour}, sort_keys=False), encoding="utf-8")
    return path


def test_validate_summarises_the_tour(tmp_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["branding", "init", "--dir", str(tmp_path)])
    result = runner.invoke(cli, ["branding", "validate", "--file", str(tmp_path / "branding.yaml")])
    assert result.exit_code == 0, result.output
    assert "tour: enabled, 0 custom step(s), 0 hidden" in result.output
    assert "warning:" not in result.output


def test_validate_reports_tour_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    path = _kit_with_tour(
        runner,
        tmp_path,
        {
            "steps": [
                {"id": "eis-key", "title": "One", "content": "First"},
                {"id": "eis-key", "title": "Two", "content": "Second"},
            ]
        },
    )
    result = runner.invoke(cli, ["branding", "validate", "--file", str(path)])
    assert result.exit_code == 1
    assert "duplicate step id 'eis-key'" in result.output


def test_validate_warns_on_unknown_permission_key(tmp_path: Path) -> None:
    runner = CliRunner()
    path = _kit_with_tour(
        runner,
        tmp_path,
        {
            "enabled": False,
            "hide": ["nav-agents"],
            "steps": [
                {
                    "id": "eis-key",
                    "title": "One",
                    "content": "First",
                    "permissions": ["apikey:manage", "vault:enroll"],
                }
            ],
        },
    )
    result = runner.invoke(cli, ["branding", "validate", "--file", str(path)])
    assert result.exit_code == 0, result.output
    assert "tour: disabled, 1 custom step(s), 1 hidden" in result.output
    assert (
        "warning: tour step 'eis-key' permission 'vault:enroll' is not in this build's catalog"
        in result.output
    )
    assert "apikey:manage" not in result.output
