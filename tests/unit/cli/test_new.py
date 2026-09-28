"""`synapse-cli new` renders a product that depends on the framework (P5 / WS-J3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from synapse_saas.cli import cli
from synapse_saas.scaffold import framework_migration_head, generate, list_templates, package_name


class TestHelpers:
    def test_package_name_is_importable(self) -> None:
        assert package_name("my-fitness-app") == "my_fitness_app"
        assert package_name("Gym Booking!!") == "gym_booking"
        assert package_name("42things") == "app_42things"

    def test_templates_listed(self) -> None:
        names = {t.name for t in list_templates()}
        assert "hello-saas" in names
        assert all(t.description for t in list_templates())

    def test_framework_head_is_the_latest_migration(self) -> None:
        head = framework_migration_head()
        assert re.match(r"^\d{4}_", head), head


class TestGenerate:
    def test_renders_a_complete_project(self, tmp_path: Path) -> None:
        written = generate("gym-booking", destination=tmp_path / "gym-booking")
        rel = {str(p.relative_to(tmp_path / "gym-booking")) for p in written}
        assert {
            "pyproject.toml",
            ".python-version",
            "README.md",
            ".env.example",
            "Makefile",
            "Dockerfile",
            "docker-compose.yml",
            "config/plans.yaml",
            "src/gym_booking/__init__.py",
            "src/gym_booking/app.py",
            "src/gym_booking/models.py",
            "src/gym_booking/router.py",
            "src/gym_booking/worker.py",
            "src/gym_booking/migrate.py",
            "migrations/alembic.ini",
            "migrations/env.py",
            "migrations/versions/0001_gym_booking_projects.py",
            "tests/conftest.py",
            "tests/test_projects.py",
        } <= rel
        assert not any(name.endswith(".tmpl") for name in rel)
        assert not any("$" in name for name in rel)

        pyproject = (tmp_path / "gym-booking" / "pyproject.toml").read_text()
        assert 'name = "gym-booking"' in pyproject
        assert re.search(r'"synapse-saas>=\d+\.\d+\.\d+,<[\d.]+"', pyproject), pyproject
        assert "[tool.uv.sources]" not in pyproject  # PyPI by default

        migration = (
            tmp_path / "gym-booking" / "migrations/versions/0001_gym_booking_projects.py"
        ).read_text()
        assert f'depends_on: Union[str, Sequence[str], None] = "{framework_migration_head()}"' in migration
        assert 'branch_labels: Union[str, Sequence[str], None] = ("gym_booking",)' in migration
        assert '"gym_booking_projects"' in migration

        for rendered in written:
            text = rendered.read_text()
            assert "$package" not in text and "$product" not in text, rendered
            assert "${package}" not in text, rendered

    def test_framework_path_adds_a_uv_source(self, tmp_path: Path) -> None:
        generate("demo", destination=tmp_path / "demo", framework_path=str(tmp_path))
        pyproject = (tmp_path / "demo" / "pyproject.toml").read_text()
        assert "[tool.uv.sources]" in pyproject
        assert f'synapse-saas = {{ path = "{tmp_path.resolve()}", editable = true }}' in pyproject

    def test_refuses_a_non_empty_destination(self, tmp_path: Path) -> None:
        (tmp_path / "taken").mkdir()
        (tmp_path / "taken" / "x").write_text("x")
        with pytest.raises(FileExistsError):
            generate("taken", destination=tmp_path / "taken")

    def test_unknown_template(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown template"):
            generate("x", destination=tmp_path / "x", template="nope")

    def test_generated_python_parses(self, tmp_path: Path) -> None:
        import ast

        for path in generate("parse-me", destination=tmp_path / "parse-me"):
            if path.suffix == ".py":
                ast.parse(path.read_text(), filename=str(path))


class TestCli:
    def test_new_and_list(self, tmp_path: Path) -> None:
        runner = CliRunner()
        listed = runner.invoke(cli, ["new", "--list-templates"])
        assert listed.exit_code == 0 and "hello-saas" in listed.output
        result = runner.invoke(cli, ["new", "acme-crm", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "acme-crm" / "src" / "acme_crm" / "app.py").exists()
        assert "uv sync" in result.output

    def test_name_required(self) -> None:
        result = CliRunner().invoke(cli, ["new"])
        assert result.exit_code != 0 and "NAME is required" in result.output
