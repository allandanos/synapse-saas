"""Branding routes on the in-process app (no DB: the lifespan never runs)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from httpx import ASGITransport, AsyncClient, Response

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63f8cfc0f01f0005000201a5d3b0e1"
    "0000000049454e44ae426082"
)


async def _get(*paths: str) -> list[Response]:
    """GET each path on a fresh app (built after the fixture set the branding)."""
    from synapse_saas.api.app import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as client:
        return [await client.get(path) for path in paths]


class TestBrandingJson:
    async def test_custom_brand_round_trips(self, custom_branding: Callable[..., Path]) -> None:
        custom_branding(
            name="Acme Widgets",
            tagline="Widgets, as a service",
            logo_dark="logo-dark.png",
            custom_css="custom.css",
            colors={"primary": "#ff5500"},
            links={"terms": "https://acme.example.com/terms", "support_email": "help@acme.example.com"},
            email={"from_name": "Acme Mailer", "footer": "secret footer"},
            invoice={"legal_name": "Acme Widgets Inc.", "tax_id": "T-1"},
            landing="redirect",
            powered_by=False,
            files={"logo-dark.png": PNG_1PX, "custom.css": b":root{--x:1}"},
        )
        [res] = await _get("/v1/branding")
        assert res.status_code == 200, res.text
        assert res.headers["cache-control"] == "public, max-age=60"
        body = res.json()
        assert body["name"] == "Acme Widgets"
        assert body["tagline"] == "Widgets, as a service"
        assert body["colors"]["primary"] == "#ff5500"
        assert body["links"]["terms"] == "https://acme.example.com/terms"
        assert body["landing"] == "redirect"
        assert body["powered_by"] is False
        assert set(body["assets"]) == {"logo", "logo_dark", "favicon", "custom_css"}
        assert body["assets"]["logo_dark"].startswith("/v1/branding/assets/logo-dark.png?v=")
        # email/invoice settings never leave the API
        assert "email" not in body and "invoice" not in body
        assert "secret footer" not in res.text and "T-1" not in res.text

    async def test_unset_assets_are_null(self, custom_branding: Callable[..., Path]) -> None:
        custom_branding(logo=None, favicon=None)
        [res] = await _get("/v1/branding")
        body = res.json()
        assert body["assets"] == {"logo": None, "logo_dark": None, "favicon": None, "custom_css": None}


class TestBrandingAssets:
    async def test_png_and_css_media_types(self, custom_branding: Callable[..., Path]) -> None:
        custom_branding(
            logo="mark.png", custom_css="custom.css", files={"mark.png": PNG_1PX, "custom.css": b"a{}"}
        )
        png, css = await _get("/v1/branding/assets/mark.png", "/v1/branding/assets/custom.css")
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
        assert png.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" not in png.headers
        assert png.content == PNG_1PX
        assert css.headers["content-type"].startswith("text/css")

    async def test_svg_is_sandboxed(self) -> None:
        [res] = await _get("/v1/branding/assets/logo.svg")
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/svg+xml"
        assert res.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'"
        assert res.headers["content-disposition"] == "inline"
        assert res.headers["cache-control"] == "public, max-age=86400"

    async def test_only_served_assets_are_reachable(self, custom_branding: Callable[..., Path]) -> None:
        custom_branding(invoice={"logo": "invoice.png"}, files={"invoice.png": PNG_1PX, "stray.svg": b"x"})
        paths = (
            "/v1/branding/assets/invoice.png",  # referenced, but PDF-only
            "/v1/branding/assets/stray.svg",  # on disk, not referenced
            "/v1/branding/assets/branding.yaml",
            "/v1/branding/assets/..%2Fbranding.yaml",
            "/v1/branding/assets/%2e%2e",
        )
        for path, res in zip(paths, await _get(*paths), strict=True):
            assert res.status_code == 404, path
            assert res.json()["type"] == "https://synapse-saas.dev/problems/not_found", path
