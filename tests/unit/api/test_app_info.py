"""App metadata: OpenAPI title from branding, framework version from the package."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from pathlib import Path

import pytest


def test_framework_version_matches_the_package() -> None:
    from synapse_saas.api.app import FRAMEWORK_VERSION

    assert importlib.metadata.version("synapse-saas") == FRAMEWORK_VERSION


def test_default_title_and_description() -> None:
    from synapse_saas.api.app import create_app

    app = create_app()
    assert app.title == "Synapse API"
    assert app.description == "Open-source multi-tenant SaaS framework"


async def test_branded_title_and_meta(custom_branding: Callable[..., Path]) -> None:
    from httpx import ASGITransport, AsyncClient

    from synapse_saas.api.app import DEFAULT_API_DESCRIPTION, FRAMEWORK_VERSION, create_app

    custom_branding(name="Acme Widgets", tagline=None)
    app = create_app()
    assert app.title == "Acme Widgets API"
    assert app.description == DEFAULT_API_DESCRIPTION
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        meta = (await client.get("/v1/meta")).json()
    assert meta["product"] == "Acme Widgets"
    assert meta["framework"] == "synapse-saas"
    assert meta["version"] == FRAMEWORK_VERSION


def test_broken_branding_stops_the_app(custom_branding: Callable[..., Path]) -> None:
    from synapse_saas.api.app import create_app
    from synapse_saas.core.errors import BrandingInvalidError

    path = custom_branding()
    (path.parent / "logo.svg").unlink()
    with pytest.raises(BrandingInvalidError, match=r"logo\.svg"):
        create_app()


async def test_broken_branding_stops_the_worker(custom_branding: Callable[..., Path]) -> None:
    from synapse_saas.core.errors import BrandingInvalidError
    from synapse_saas.worker.jobs import WorkerSettings

    custom_branding(colors={"primary": "nope"})
    with pytest.raises(BrandingInvalidError):
        await WorkerSettings.on_startup({})
