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


def _step(**overrides: Any) -> dict[str, Any]:
    return {"id": "eis-api-key", "title": "Create your key", "content": "Make one here.", **overrides}


class TestTour:
    def test_defaults_are_enabled_and_empty(self) -> None:
        tour = Branding.model_validate(_brand()).tour
        assert tour.enabled is True
        assert tour.hide == []
        assert tour.steps == []

    def test_custom_steps_round_trip(self) -> None:
        step = _step(
            anchor="nav-api-keys",
            side="right-top",
            after="nav-api-keys",
            roles=["owner", "custom_role"],
            permissions=["apikey:manage"],
            icon="key",
            link={"label": "Enroll it", "href": "https://acme.example.com/enroll"},
        )
        brand = Branding.model_validate(
            _brand(tour={"enabled": False, "hide": ["nav-agents"], "steps": [step, _step(id="centred")]})
        )
        tour = brand.tour
        assert tour.enabled is False
        assert tour.hide == ["nav-agents"]
        first, second = tour.steps
        assert first.model_dump() == {
            **step,
            "link": {"label": "Enroll it", "href": "https://acme.example.com/enroll"},
        }
        assert second.anchor is None and second.side is None and second.after is None
        assert second.roles is None and second.permissions is None and second.link is None
        assert second.icon == "sparkles"

    def test_commented_out_section_parses_as_defaults(self) -> None:
        tour = Branding.model_validate(_brand(tour=None)).tour
        assert tour.enabled is True and tour.steps == [] and tour.hide == []

    def test_enum_tuples_match_the_console(self) -> None:
        from synapse_saas.branding.models import BUILTIN_STEP_IDS, TOUR_ANCHORS, TOUR_ICONS, TOUR_SIDES

        assert (
            len(BUILTIN_STEP_IDS) == 14
            and BUILTIN_STEP_IDS[0] == "welcome"
            and BUILTIN_STEP_IDS[-1] == "done"
        )
        assert len(TOUR_ANCHORS) == 16 and "take-the-tour" in TOUR_ANCHORS
        assert len(TOUR_SIDES) == 12
        assert len(TOUR_ICONS) == 22 and "sparkles" in TOUR_ICONS

    @pytest.mark.parametrize(
        ("tour", "loc"),
        [
            ({"steps": [_step(id="welcome")]}, ("tour", "steps", 0, "id")),  # a built-in id
            ({"steps": [_step(), _step()]}, ("tour",)),  # duplicate ids (model validator)
            ({"hide": ["nav-agents", "nav-agents"]}, ("tour",)),  # duplicate hide (model validator)
            ({"steps": [_step(id=f"s{i}") for i in range(21)]}, ("tour", "steps")),
            ({"steps": [_step(anchor="nav-everything")]}, ("tour", "steps", 0, "anchor")),
            ({"steps": [_step(side="middle")]}, ("tour", "steps", 0, "side")),
            ({"steps": [_step(icon="unicorn")]}, ("tour", "steps", 0, "icon")),
            ({"steps": [_step(after="eis-other")]}, ("tour", "steps", 0, "after")),
            ({"hide": ["nav-unknown"]}, ("tour", "hide", 0)),
            ({"steps": [_step(id="Bad_Id")]}, ("tour", "steps", 0, "id")),
            ({"steps": [_step(title="x" * 81)]}, ("tour", "steps", 0, "title")),
            ({"steps": [_step(title="")]}, ("tour", "steps", 0, "title")),
            ({"steps": [_step(content="line one\nline two")]}, ("tour", "steps", 0, "content")),
            ({"steps": [_step(content="x" * 401)]}, ("tour", "steps", 0, "content")),
            ({"steps": [_step(roles=["Owner"])]}, ("tour", "steps", 0, "roles", 0)),
            ({"steps": [_step(roles=[])]}, ("tour", "steps", 0, "roles")),
            ({"steps": [_step(roles=[f"role_{i}" for i in range(11)])]}, ("tour", "steps", 0, "roles")),
            ({"steps": [_step(permissions=["apikey-manage"])]}, ("tour", "steps", 0, "permissions", 0)),
            (
                {"steps": [_step(link={"label": "Go", "href": "javascript:alert(1)"})]},
                ("tour", "steps", 0, "link", "href"),
            ),
            (
                {"steps": [_step(link={"label": "Go", "href": "/accreditation"})]},
                ("tour", "steps", 0, "link", "href"),
            ),
            (
                {"steps": [_step(link={"label": "Go", "href": "ftp://example.com/x"})]},
                ("tour", "steps", 0, "link", "href"),
            ),
            (
                {"steps": [_step(link={"label": "x" * 41, "href": "https://example.com"})]},
                ("tour", "steps", 0, "link", "label"),
            ),
            ({"steps": [_step(link={"label": "Go"})]}, ("tour", "steps", 0, "link", "href")),
            ({"steps": [_step(color="red")]}, ("tour", "steps", 0, "color")),  # unknown key in a step
            ({"version": 2}, ("tour", "version")),  # unknown key in the section
            ({"enabled": None}, ("tour", "enabled")),  # `enabled` stays strict
        ],
    )
    def test_invalid_tour(self, tour: dict[str, Any], loc: tuple[str | int, ...]) -> None:
        with pytest.raises(ValidationError) as excinfo:
            Branding.model_validate(_brand(tour=tour))
        assert loc in [error["loc"] for error in excinfo.value.errors()]

    def test_hiding_the_step_another_follows_is_valid(self) -> None:
        """Hiding never invalidates a kit: `after` may name a hidden built-in step."""
        tour = Branding.model_validate(
            _brand(tour={"hide": ["nav-agents"], "steps": [_step(after="nav-agents")]})
        ).tour
        assert tour.hide == ["nav-agents"]
        assert tour.steps[0].after == "nav-agents"

    def test_bare_hide_and_steps_keys_are_empty_lists(self) -> None:
        tour = Branding.model_validate(_brand(tour={"enabled": True, "hide": None, "steps": None})).tour
        assert tour.hide == [] and tour.steps == []

    @pytest.mark.parametrize(
        ("tour", "message"),
        [
            ({"steps": [_step(id="done")]}, "'done' is a built-in step id"),
            ({"steps": [_step(), _step()]}, "duplicate step id 'eis-api-key'"),
            ({"hide": ["plan", "plan"]}, "duplicate hide entry 'plan'"),
        ],
    )
    def test_tour_errors_name_the_offender(self, tour: dict[str, Any], message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            Branding.model_validate(_brand(tour=tour))
