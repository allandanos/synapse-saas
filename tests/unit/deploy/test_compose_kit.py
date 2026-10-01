"""deploy/compose/ defaults to the images of THIS release: bumping the package
version without moving the kit's image tag (or vice versa) fails here."""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
KIT = REPO_ROOT / "deploy" / "compose"
VERSION_DEFAULT = re.compile(r"\$\{SYNAPSE_VERSION:-([^}]*)\}")


def _package_version() -> str:
    return importlib.metadata.version("synapse-saas")


def test_compose_image_tags_default_to_the_package_version() -> None:
    compose = (KIT / "docker-compose.yml").read_text(encoding="utf-8")
    defaults = VERSION_DEFAULT.findall(compose)
    assert len(defaults) == 2, defaults  # the shared api image (api/worker/migrate) + web
    assert set(defaults) == {_package_version()}


def test_env_example_pins_the_package_version() -> None:
    env = (KIT / ".env.example").read_text(encoding="utf-8")
    pinned = re.findall(r"^SYNAPSE_VERSION=(.*)$", env, flags=re.MULTILINE)
    assert pinned == [_package_version()]


def test_console_package_version_matches() -> None:
    """release.yml refuses to publish when these differ; fail earlier, locally."""
    package = json.loads((REPO_ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == _package_version()


def test_every_service_image_follows_prefix_and_version() -> None:
    services = yaml.safe_load((KIT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    for name in ("migrate", "api", "worker", "web"):
        image = services[name]["image"]
        assert image.startswith("${SYNAPSE_IMAGE_PREFIX:-allandanos}/synapse-saas-"), (name, image)
        assert VERSION_DEFAULT.search(image), (name, image)
