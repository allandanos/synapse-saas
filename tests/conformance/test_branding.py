"""Branding: the console's public presentation surface (no auth, no tenant)."""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient

from tests.conformance.conftest import assert_problem

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


async def test_branding_document(api: AsyncClient) -> None:
    res = await api.get("/v1/branding")
    assert res.status_code == 200, res.text
    assert "max-age=60" in res.headers["cache-control"]
    body = res.json()
    assert set(body) == {"name", "tagline", "assets", "colors", "links", "landing", "powered_by"}, body
    assert isinstance(body["name"], str) and body["name"]
    assert set(body["assets"]) == {"logo", "logo_dark", "favicon", "custom_css"}
    for url in body["assets"].values():
        # origin-relative: the console fetches JSON internally, browsers load assets publicly
        assert url is None or url.startswith("/v1/branding/assets/"), url
    assert {"primary", "primary_foreground", "accent", "radius"} <= set(body["colors"])
    assert all(HEX.match(body["colors"][key]) for key in ("primary", "primary_foreground", "accent"))
    assert body["landing"] in {"page", "redirect"}
    assert isinstance(body["powered_by"], bool)


async def test_svg_logo_is_served_sandboxed(api: AsyncClient) -> None:
    logo = (await api.get("/v1/branding")).json()["assets"]["logo"]
    if logo is None or ".svg" not in logo:
        pytest.skip("the deployment under test ships no SVG logo")
    res = await api.get(logo)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in res.headers["content-security-policy"]
    assert b"<svg" in res.content


async def test_unknown_and_traversal_assets_are_404_problems(api: AsyncClient) -> None:
    for path in (
        "/v1/branding/assets/not-a-brand-asset.svg",
        "/v1/branding/assets/branding.yaml",
        "/v1/branding/assets/%2e%2e",
        "/v1/branding/assets/..%2Fbranding.yaml",
    ):
        assert_problem(await api.get(path), 404)
