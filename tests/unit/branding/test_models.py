"""Branding schema: defaults, forbid, formats, asset-name and extension rules."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from synapse_saas.branding.models import Branding


def _brand(**overrides: Any) -> dict[str, Any]:
    return {"version": 1, "name": "Acme", **overrides}


class TestDefaults:
    def test_minimal_file_gets_every_default(self) -> None:
        brand = Branding.model_validate(_brand())
        assert brand.colors.primary == "#18181b"
        assert brand.colors.primary_foreground == "#ffffff"
        assert brand.colors.accent == "#2563eb"
        assert brand.colors.radius == "0.5rem"
        assert brand.landing == "page"
        assert brand.powered_by is True
        assert brand.served_assets == {}
        assert brand.referenced_assets == frozenset()

    def test_effective_names_fall_back_to_the_brand_name(self) -> None:
        brand = Branding.model_validate(_brand())
        assert brand.effective_from_name == "Acme"
        assert brand.effective_legal_name == "Acme"
        custom = Branding.model_validate(
            _brand(email={"from_name": "Acme Billing"}, invoice={"legal_name": "Acme Widgets Inc."})
        )
        assert custom.effective_from_name == "Acme Billing"
        assert custom.effective_legal_name == "Acme Widgets Inc."

    def test_sections_with_every_key_commented_out_parse_as_empty(self) -> None:
        brand = Branding.model_validate(_brand(email=None, invoice=None, links=None, colors=None))
        assert brand.email.from_name is None
        assert brand.invoice.address_lines == []

    def test_models_are_immutable(self) -> None:
        brand = Branding.model_validate(_brand())
        with pytest.raises(ValidationError):
            brand.name = "Other"  # type: ignore[misc]


class TestRejections:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"version": 2},
            {"name": ""},
            {"name": "x" * 61},
            {"unknown_key": True},
            {"colors": {"primary": "red"}},
            {"colors": {"accent": "#12345"}},
            {"colors": {"radius": "8"}},
            {"colors": {"radius": "1vh"}},
            {"colors": {"shade": "#000000"}},
            {"links": {"website": "javascript:alert(1)"}},
            {"links": {"support_email": "not-an-email"}},
            {"invoice": {"address_lines": ["l"] * 7}},
            {"landing": "home"},
            # control characters break email headers (Subject/From) and PDF cells
            {"name": "Acme\nWidgets"},
            {"name": "Acme\x00"},
            {"name": "Acme\x7f"},
            {"tagline": "line one\r\nline two"},
            {"email": {"from_name": "Acme\r\nBcc: x@example.com"}},
            {"email": {"footer": "nul\x00byte"}},
            {"invoice": {"legal_name": "Acme\tInc."}},
            {"invoice": {"tax_id": "TIN\n1"}},
            {"invoice": {"address_lines": ["1 Example St", "line\nbreak"]}},
            {"invoice": {"footer": "nul\x00byte"}},
        ],
    )
    def test_invalid_values(self, overrides: dict[str, Any]) -> None:
        with pytest.raises(ValidationError):
            Branding.model_validate(_brand(**overrides))

    def test_footers_may_span_lines(self) -> None:
        brand = Branding.model_validate(
            _brand(email={"footer": "Acme\nhttps://acme.example.com"}, invoice={"footer": "a\tb\nc"})
        )
        assert "\n" in (brand.email.footer or "")

    def test_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            Branding.model_validate({"version": 1})

    @pytest.mark.parametrize(
        "name", ["../x.svg", "a/b.png", ".hidden.svg", "a\\b.svg", "", "x" * 70 + ".svg"]
    )
    def test_asset_names_are_bare_file_names(self, name: str) -> None:
        with pytest.raises(ValidationError):
            Branding.model_validate(_brand(logo=name))

    @pytest.mark.parametrize(
        ("field", "name"),
        [
            ("logo", "logo.gif"),
            ("logo_dark", "logo.jpg"),
            ("favicon", "favicon.gif"),
            ("custom_css", "theme.scss"),
            ("custom_css", "logo.svg"),
        ],
    )
    def test_per_field_extension_allow_list(self, field: str, name: str) -> None:
        with pytest.raises(ValidationError):
            Branding.model_validate(_brand(**{field: name}))

    def test_invoice_logo_extension(self) -> None:
        with pytest.raises(ValidationError):
            Branding.model_validate(_brand(invoice={"logo": "mark.webp"}))

    def test_allowed_extensions(self) -> None:
        brand = Branding.model_validate(
            _brand(
                logo="Logo.PNG",
                logo_dark="logo-dark.svg",
                favicon="favicon.ico",
                custom_css="custom.css",
                invoice={"logo": "invoice_logo.png"},
            )
        )
        assert brand.served_assets == {
            "logo": "Logo.PNG",
            "logo_dark": "logo-dark.svg",
            "favicon": "favicon.ico",
            "custom_css": "custom.css",
        }
        # invoice.logo must exist on disk but is never served
        assert "invoice_logo.png" in brand.referenced_assets
        assert "invoice_logo.png" not in brand.served_assets.values()


class TestAssetPath:
    def test_unloaded_branding_resolves_nothing(self) -> None:
        from synapse_saas.core.errors import NotFoundError

        brand = Branding.model_validate(_brand(logo="logo.svg"))
        with pytest.raises(NotFoundError):
            brand.asset_path("logo.svg")

    def test_asset_url_is_origin_relative(self) -> None:
        brand = Branding.model_validate(_brand(logo="logo.svg"))
        assert brand.asset_url("logo.svg") == "/v1/branding/assets/logo.svg"
