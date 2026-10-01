"""Branding loader: one file + its assets directory → a validated `Branding`.

Shaped like `subscriptions.catalog.load_catalog`: a missing file, bad YAML, a
schema violation or a missing referenced asset all raise ONE
`BrandingInvalidError` carrying every error, so `create_app()` and the worker
refuse to start with a precise message. Resolved once per process
(`get_branding()`); restart to apply changes.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import shutil
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from synapse_saas.branding.models import Branding
from synapse_saas.core.errors import BrandingInvalidError, NotFoundError

MEDIA_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".css": "text/css",
}
DIGEST_LENGTH = 8


def default_kit_dir() -> Path:
    """The packaged starter kit (branding.yaml + logo.svg + favicon.svg)."""
    return Path(str(importlib.resources.files("synapse_saas") / "config" / "branding"))


def _validation_messages(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()]


def _invalid(message: str, path: Path, errors: list[str]) -> BrandingInvalidError:
    return BrandingInvalidError(message, extras={"path": str(path), "errors": errors})


def load_branding(path: str | Path | None = None) -> Branding:
    """Load + validate branding and its assets. Raises BrandingInvalidError with all errors at once."""
    from synapse_saas.core.config import get_settings

    resolved = Path(path) if path is not None else Path(get_settings().branding_file)
    if not resolved.is_file():
        message = f"Branding file not found: {resolved}"
        raise _invalid(message, resolved, [message])
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        message = f"Branding file is not valid YAML: {exc}"
        raise _invalid(message, resolved, [message]) from exc
    except (OSError, UnicodeDecodeError) as exc:  # unreadable, or not UTF-8
        message = f"Branding file could not be read: {exc}"
        raise _invalid(message, resolved, [message]) from exc
    try:
        branding = Branding.model_validate(raw)
    except ValidationError as exc:
        errors = _validation_messages(exc)
        raise _invalid(
            f"Branding file failed validation ({len(errors)} error(s)): " + "; ".join(errors),
            resolved,
            errors,
        ) from exc

    # Absolute, so a relative SYNAPSE_BRANDING_FILE never depends on the cwd at request time
    branding._source = resolved.resolve()
    digests: dict[str, str] = {}
    missing: list[str] = []
    asset_errors: list[str] = []
    for name in sorted(branding.referenced_assets):
        try:
            asset = branding.asset_path(name)
        except NotFoundError:
            missing.append(name)
            asset_errors.append(f"asset not found in {resolved.parent}: {name}")
            continue
        try:
            digests[name] = hashlib.sha256(asset.read_bytes()).hexdigest()[:DIGEST_LENGTH]
        except OSError as exc:
            missing.append(name)
            asset_errors.append(f"asset could not be read: {name} ({exc.strerror or exc})")
    if asset_errors:
        raise _invalid(
            f"Branding references missing or unreadable assets: {', '.join(missing)}", resolved, asset_errors
        )
    branding._digests = digests
    return branding


@lru_cache(maxsize=1)
def get_branding() -> Branding:
    """The deployment's branding, loaded once per process (the per-org seam lives here)."""
    return load_branding()


def reset_branding() -> None:
    """Drop the cached branding (tests; a future reload hook)."""
    get_branding.cache_clear()


def asset_media_type(name: str) -> str:
    return MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def write_starter_kit(directory: str | Path, *, force: bool = False) -> list[Path]:
    """Copy the packaged kit into `directory`. Refuses to overwrite unless `force`."""
    target = Path(directory)
    sources = sorted(p for p in default_kit_dir().iterdir() if p.is_file() and not p.name.startswith("."))
    clashes = [target / src.name for src in sources if (target / src.name).exists()]
    if clashes and not force:
        raise FileExistsError("refusing to overwrite (use --force): " + ", ".join(str(c) for c in clashes))
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for src in sources:
        destination = target / src.name
        shutil.copyfile(src, destination)
        written.append(destination)
    return written
