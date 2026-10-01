"""synapse-cli branding init|validate."""

from __future__ import annotations

from pathlib import Path

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
