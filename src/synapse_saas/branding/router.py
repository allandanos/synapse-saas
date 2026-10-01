"""Public branding surface: the console's presentation config + whitelisted assets.

No auth, no tenant: the console renders login and landing pages from it.
Only the presentation subset leaves the API — email and invoice settings stay
in-process. Asset URLs are origin-relative (the console fetches this JSON over
its internal API URL; browsers load assets from the public one).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from synapse_saas.branding.loader import MEDIA_TYPES, asset_media_type, get_branding
from synapse_saas.branding.models import BrandColors, BrandLinks
from synapse_saas.core.errors import NotFoundError

router = APIRouter(prefix="/branding", tags=["branding"])

BRANDING_MAX_AGE = 60
ASSET_MAX_AGE = 86400
# An operator-supplied SVG opened directly must not run script or load anything.
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"


class BrandingAssets(BaseModel):
    logo: str | None = None
    logo_dark: str | None = None
    favicon: str | None = None
    custom_css: str | None = None


class BrandingRead(BaseModel):
    name: str
    tagline: str | None
    assets: BrandingAssets
    colors: BrandColors
    links: BrandLinks
    landing: Literal["page", "redirect"]
    powered_by: bool


@router.get("", response_model=BrandingRead)
async def read_branding(response: Response) -> BrandingRead:
    """The deployment's presentation branding (name, assets, colours, links)."""
    brand = get_branding()
    response.headers["Cache-Control"] = f"public, max-age={BRANDING_MAX_AGE}"
    return BrandingRead(
        name=brand.name,
        tagline=brand.tagline,
        assets=BrandingAssets(
            **{field: brand.asset_url(name) for field, name in brand.served_assets.items()}
        ),
        colors=brand.colors,
        links=brand.links,
        landing=brand.landing,
        powered_by=brand.powered_by,
    )


@router.get(
    "/assets/{name}",
    response_class=FileResponse,
    responses={
        200: {
            "description": "The asset bytes",
            "content": {media_type: {} for media_type in sorted(set(MEDIA_TYPES.values()))},
        },
        404: {"description": "Not a served branding asset (RFC 7807 problem)"},
    },
)
async def read_branding_asset(name: str) -> FileResponse:
    """A branding asset named by branding.yaml (logo, logo_dark, favicon, custom_css); 404 otherwise."""
    brand = get_branding()
    if name not in brand.served_assets.values():
        raise NotFoundError("Branding asset not found")
    path = brand.asset_path(name)
    media_type = asset_media_type(name)
    headers = {
        "Cache-Control": f"public, max-age={ASSET_MAX_AGE}",
        "X-Content-Type-Options": "nosniff",
    }
    if media_type == "image/svg+xml":
        headers["Content-Security-Policy"] = SVG_CSP
        headers["Content-Disposition"] = "inline"
    return FileResponse(path, media_type=media_type, headers=headers)
