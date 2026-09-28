"""`synapse-cli new`: generate a product that DEPENDS on the framework (ADR 0011).

A template is a directory of files under `templates/<name>/`; every file is
rendered with `string.Template` (`$product`, `$package`, `$framework_spec`,
`$framework_head`, …) and written under the destination. The generated project
is not a fork: its `pyproject.toml` depends on the published package, its
migrations are an Alembic branch that `depends_on` the framework head, and its
tests run on the framework's public pytest plugin.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

TEMPLATES_ROOT = importlib.resources.files("synapse_saas") / "scaffold" / "templates"
TEMPLATE_SUFFIX = ".tmpl"


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    name: str
    description: str


def list_templates() -> list[TemplateInfo]:
    infos: list[TemplateInfo] = []
    for entry in sorted(TEMPLATES_ROOT.iterdir(), key=lambda e: e.name):
        if entry.is_dir():
            about = entry / "TEMPLATE"
            description = about.read_text().strip() if about.is_file() else ""
            infos.append(TemplateInfo(name=entry.name, description=description))
    return infos


def package_name(product: str) -> str:
    """`my-fitness-app` → `my_fitness_app` (a valid importable package name)."""
    package = re.sub(r"[^a-z0-9_]", "_", product.strip().lower().replace("-", "_"))
    package = re.sub(r"_+", "_", package).strip("_")
    if not package or package[0].isdigit():
        package = f"app_{package}"
    return package


def framework_version_spec() -> str:
    """`>=0.1.0,<0.2` for 0.x (minor is breaking), `>=1.2.0,<2` afterwards."""
    try:
        version = importlib.metadata.version("synapse-saas")
    except importlib.metadata.PackageNotFoundError:
        version = "0.1.0"
    major, minor, *_ = [*version.split("."), "0", "0"][:3]
    base = f"{major}.{minor}.0"
    upper = f"{major}.{int(minor) + 1}" if major == "0" else str(int(major) + 1)
    return f">={base},<{upper}"


def framework_migration_head() -> str:
    """The framework revision a product's first migration must depend on."""
    from alembic.script import ScriptDirectory

    from synapse_saas.cli import alembic_config

    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one framework migration head, found {heads}")
    return heads[0]


def framework_versions_dir() -> str:
    return str(importlib.resources.files("synapse_saas") / "migrations" / "versions")


def render_context(product: str, *, framework_path: str | None = None) -> dict[str, Any]:
    package = package_name(product)
    uv_source = ""
    if framework_path:
        resolved = str(Path(framework_path).resolve())
        uv_source = f'\n[tool.uv.sources]\nsynapse-saas = {{ path = "{resolved}", editable = true }}\n'
    return {
        "product": product,
        "package": package,
        "package_title": package.replace("_", " ").title(),
        "framework_spec": framework_version_spec(),
        "framework_head": framework_migration_head(),
        "framework_versions_dir": framework_versions_dir(),
        "uv_source": uv_source,
    }


def generate(
    product: str,
    *,
    destination: Path,
    template: str = "hello-saas",
    framework_path: str | None = None,
) -> list[Path]:
    """Render `template` into `destination` (must not exist or be empty). Returns the files written."""
    source = TEMPLATES_ROOT / template
    if not source.is_dir():
        known = ", ".join(t.name for t in list_templates())
        raise ValueError(f"unknown template {template!r}; known: {known}")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"{destination} exists and is not empty")

    context = render_context(product, framework_path=framework_path)
    written: list[Path] = []
    for entry in _walk(source):
        relative = str(entry).replace(str(source), "", 1).lstrip("/")
        if relative == "TEMPLATE":
            continue
        target_rel = Template(relative).safe_substitute(context)
        target_rel = target_rel.removesuffix(TEMPLATE_SUFFIX)
        target = destination / target_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        content = entry.read_text()
        target.write_text(Template(content).safe_substitute(context))
        written.append(target)
    return written


def _walk(root: Any) -> list[Any]:
    files: list[Any] = []
    for entry in root.iterdir():
        if entry.is_dir():
            files.extend(_walk(entry))
        else:
            files.append(entry)
    return sorted(files, key=str)
