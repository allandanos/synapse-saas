"""Branding schema: YAML → validated, immutable pydantic models.

Mirrors the plan catalog (`subscriptions/catalog.py`): every model forbids
unknown keys so a typo fails at startup instead of silently doing nothing.
Asset fields hold bare file names resolved against the directory that holds
`branding.yaml`; the loader sets that directory and the per-asset digests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from synapse_saas.core.errors import NotFoundError

# Single-line text lands in email headers (Subject, From) and PDF cells: no control
# characters at all. Multi-line footers may carry newlines/tabs, never NUL.
SINGLE_LINE = r"^[^\x00-\x1f\x7f]+$"
MULTI_LINE = r"^[^\x00]+$"

HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
CssLength = Annotated[str, Field(pattern=r"^\d+(\.\d+)?(px|rem|em)$")]
WebUrl = Annotated[str, Field(pattern=r"^https?://[^\s<>\"']+$", max_length=2048)]
# A bare file name: no separators, no leading dot (no hidden files, no `..`).
AssetName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]

LOGO_EXTENSIONS = frozenset({".svg", ".png"})
FAVICON_EXTENSIONS = frozenset({".ico", ".png", ".svg"})
CSS_EXTENSIONS = frozenset({".css"})

# Assets the API serves to browsers. `invoice.logo` is read in-process only.
SERVED_ASSET_FIELDS = ("logo", "logo_dark", "favicon", "custom_css")


def _check_extension(name: str | None, allowed: frozenset[str]) -> str | None:
    if name is not None and Path(name).suffix.lower() not in allowed:
        raise ValueError(f"{name!r} must be one of {sorted(allowed)}")
    return name


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandColors(_Strict):
    """Console theme tokens: primary actions, text drawn on them, accent, corner radius."""

    primary: HexColor = "#18181b"
    primary_foreground: HexColor = "#ffffff"
    accent: HexColor = "#2563eb"
    radius: CssLength = "0.5rem"


class BrandLinks(_Strict):
    website: WebUrl | None = None
    docs: WebUrl | None = None
    terms: WebUrl | None = None
    privacy: WebUrl | None = None
    support_email: EmailStr | None = None


class BrandEmail(_Strict):
    from_name: str | None = Field(None, min_length=1, max_length=80, pattern=SINGLE_LINE)
    footer: str | None = Field(None, min_length=1, max_length=500, pattern=MULTI_LINE)


class BrandInvoice(_Strict):
    legal_name: str | None = Field(None, min_length=1, max_length=120, pattern=SINGLE_LINE)
    address_lines: list[Annotated[str, Field(min_length=1, max_length=120, pattern=SINGLE_LINE)]] = Field(
        default_factory=list, max_length=6
    )
    tax_id: str | None = Field(None, min_length=1, max_length=60, pattern=SINGLE_LINE)
    footer: str | None = Field(None, min_length=1, max_length=200, pattern=MULTI_LINE)
    logo: AssetName | None = None

    @field_validator("logo")
    @classmethod
    def _logo_extension(cls, value: str | None) -> str | None:
        return _check_extension(value, LOGO_EXTENSIONS)


# ── Product tour ──────────────────────────────────────────────────────────────
# Mirrors the built-in step ids of `apps/web/src/components/tour/steps.tsx` and its
# `data-tour` anchors; the console mirrors these sets in `apps/web/src/lib/tour-config.ts`.
# Literals are written out (mypy rejects `Literal[*tuple]`); the tuples derive from them.

BuiltinStepId = Literal[
    "welcome",
    "org-switcher",
    "plan",
    "usage",
    "features",
    "nav-members",
    "nav-agents",
    "nav-api-keys",
    "nav-developer",
    "nav-webhooks",
    "nav-billing",
    "nav-usage",
    "nav-admin",
    "done",
]
TourAnchor = Literal[
    "org-switcher",
    "plan",
    "usage",
    "features",
    "nav-dashboard",
    "nav-members",
    "nav-agents",
    "nav-api-keys",
    "nav-developer",
    "nav-webhooks",
    "nav-billing",
    "nav-usage",
    "nav-audit",
    "nav-settings",
    "nav-admin",
    "take-the-tour",
]
# = nextstepjs `Step["side"]`
TourSide = Literal[
    "top",
    "bottom",
    "left",
    "right",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "left-top",
    "left-bottom",
    "right-top",
    "right-bottom",
]
TourIcon = Literal[
    "sparkles",
    "compass",
    "building",
    "receipt",
    "gauge",
    "toggle",
    "users",
    "bot",
    "key",
    "code",
    "webhook",
    "credit-card",
    "chart",
    "shield",
    "rocket",
    "link",
    "mail",
    "file",
    "clipboard",
    "plug",
    "book",
    "lightbulb",
]

BUILTIN_STEP_IDS: tuple[str, ...] = get_args(BuiltinStepId)
TOUR_ANCHORS: tuple[str, ...] = get_args(TourAnchor)
TOUR_SIDES: tuple[str, ...] = get_args(TourSide)
TOUR_ICONS: tuple[str, ...] = get_args(TourIcon)
MAX_TOUR_STEPS = 20

StepId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")]
# Same shape as a role key (`authorization/schemas.py` RoleCreate.key): custom roles allowed.
RoleKey = Annotated[str, Field(pattern=r"^[a-z0-9_]{2,64}$")]
# Pattern only: keys outside this build's catalog are a `branding validate` warning (forks extend it).
PermissionKey = Annotated[str, Field(pattern=r"^[a-z][a-z_]*:[a-z][a-z_]*$")]


def _first_duplicate(values: list[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


class TourStepLink(_Strict):
    """Call to action under a step's text; opens in a new tab."""

    label: str = Field(min_length=1, max_length=40, pattern=SINGLE_LINE)
    href: WebUrl


class TourStep(_Strict):
    """A deployment-defined step merged into the console's welcome tour."""

    id: StepId
    title: str = Field(min_length=1, max_length=80, pattern=SINGLE_LINE)
    content: str = Field(min_length=1, max_length=400, pattern=SINGLE_LINE)
    anchor: TourAnchor | None = None
    side: TourSide | None = None
    after: BuiltinStepId | None = None
    roles: list[RoleKey] | None = Field(None, min_length=1, max_length=10)
    permissions: list[PermissionKey] | None = Field(None, min_length=1, max_length=10)
    icon: TourIcon = "sparkles"
    link: TourStepLink | None = None

    @field_validator("id")
    @classmethod
    def _not_builtin(cls, value: str) -> str:
        if value in BUILTIN_STEP_IDS:
            raise ValueError(f"{value!r} is a built-in step id")
        return value


class TourConfig(_Strict):
    """The console's product tour: on/off, built-in steps to hide, extra steps."""

    enabled: bool = True
    hide: list[BuiltinStepId] = Field(default_factory=list, max_length=len(BUILTIN_STEP_IDS))
    steps: list[TourStep] = Field(default_factory=list, max_length=MAX_TOUR_STEPS)

    @field_validator("hide", "steps", mode="before")
    @classmethod
    def _bare_key(cls, value: Any) -> Any:
        """A bare `hide:` / `steps:` (items commented out) parses as null: treat it as `[]`."""
        return [] if value is None else value

    @model_validator(mode="after")
    def _unique(self) -> TourConfig:
        duplicate_step = _first_duplicate([step.id for step in self.steps])
        if duplicate_step is not None:
            raise ValueError(f"duplicate step id {duplicate_step!r}")
        duplicate_hide = _first_duplicate(list(self.hide))
        if duplicate_hide is not None:
            raise ValueError(f"duplicate hide entry {duplicate_hide!r}")
        return self


class Branding(_Strict):
    version: Literal[1]
    name: str = Field(min_length=1, max_length=60, pattern=SINGLE_LINE)
    tagline: str | None = Field(None, min_length=1, max_length=160, pattern=SINGLE_LINE)
    logo: AssetName | None = None
    logo_dark: AssetName | None = None
    favicon: AssetName | None = None
    custom_css: AssetName | None = None
    colors: BrandColors = BrandColors()
    links: BrandLinks = BrandLinks()
    email: BrandEmail = BrandEmail()
    invoice: BrandInvoice = BrandInvoice()
    landing: Literal["page", "redirect"] = "page"
    powered_by: bool = True
    tour: TourConfig = TourConfig()

    # Set by the loader: the branding.yaml path (assets resolve next to it) and
    # sha256[:8] per referenced asset (the `?v=` cache-buster).
    _source: Path | None = PrivateAttr(default=None)
    _digests: dict[str, str] = PrivateAttr(default_factory=dict)

    @field_validator("colors", "links", "email", "invoice", "tour", mode="before")
    @classmethod
    def _empty_section(cls, value: Any) -> Any:
        """A section whose keys are all commented out parses as null: treat it as `{}`."""
        return {} if value is None else value

    @field_validator("logo", "logo_dark")
    @classmethod
    def _logo_extension(cls, value: str | None) -> str | None:
        return _check_extension(value, LOGO_EXTENSIONS)

    @field_validator("favicon")
    @classmethod
    def _favicon_extension(cls, value: str | None) -> str | None:
        return _check_extension(value, FAVICON_EXTENSIONS)

    @field_validator("custom_css")
    @classmethod
    def _css_extension(cls, value: str | None) -> str | None:
        return _check_extension(value, CSS_EXTENSIONS)

    # ── Derived values ─────────────────────────────────────────────────────────

    @property
    def effective_from_name(self) -> str:
        return self.email.from_name or self.name

    @property
    def effective_legal_name(self) -> str:
        return self.invoice.legal_name or self.name

    @property
    def served_assets(self) -> dict[str, str]:
        """Field → file name for every asset browsers may fetch (set fields only)."""
        return {field: name for field in SERVED_ASSET_FIELDS if (name := getattr(self, field)) is not None}

    @property
    def referenced_assets(self) -> frozenset[str]:
        """Every file name this branding needs on disk (served ones + `invoice.logo`)."""
        names = set(self.served_assets.values())
        if self.invoice.logo is not None:
            names.add(self.invoice.logo)
        return frozenset(names)

    @property
    def source(self) -> Path | None:
        return self._source

    @property
    def asset_dir(self) -> Path | None:
        return self._source.parent if self._source is not None else None

    def asset_digest(self, name: str) -> str | None:
        return self._digests.get(name)

    def asset_url(self, name: str) -> str:
        """Origin-relative URL: the console fetches JSON over its internal API URL,
        but the browser must load assets from the public one."""
        digest = self._digests.get(name)
        suffix = f"?v={digest}" if digest else ""
        return f"/v1/branding/assets/{name}{suffix}"

    def asset_path(self, name: str) -> Path:
        """Resolve a referenced asset; anything else (or anything escaping the
        branding directory, e.g. via a symlink) is a 404, never a file read."""
        base = self.asset_dir
        if base is None or name not in self.referenced_assets:
            raise NotFoundError("Branding asset not found")
        root = base.resolve()
        candidate = (root / name).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise NotFoundError("Branding asset not found")
        return candidate
