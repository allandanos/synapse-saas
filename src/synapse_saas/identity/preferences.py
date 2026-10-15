"""Per-user UI preferences (`users.preferences`): pure, DB-free validation.

`PATCH /v1/auth/me` merges the patch's top-level keys into the stored object.
Top-level keys are namespaces (`tours`, `sidebar_collapsed`) and must match
`PREFERENCE_KEY_RE`; anything below them is free-form JSON bounded by size
and depth. A patch over its caps is a 422 at parse time (`ValueError` inside
a pydantic validator); a merge that would outgrow the stored caps is a 422
`ValidationFailedError` from the service.

Whatever JSON or Postgres JSONB cannot hold is refused here as well, so a
request never reaches the database only to fail there: NaN/Infinity (Python's
json parser accepts them; JSON has no such literals), NUL characters (JSONB
rejects `\\u0000`), and nesting past the cap — checked iteratively, so a
5000-level payload is a 422 rather than a RecursionError.
"""

from __future__ import annotations

import json
import re
from typing import Any

from synapse_saas.core.errors import ValidationFailedError

# Matched with `fullmatch`: `$` alone would accept a trailing newline.
PREFERENCE_KEY_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}")
MAX_PATCH_KEYS = 32
MAX_PATCH_BYTES = 16_384
MAX_STORED_KEYS = 64
MAX_STORED_BYTES = 32_768
MAX_DEPTH = 8

_NUL = "\x00"


def preferences_size(value: object) -> int:
    """UTF-8 byte length of the compact JSON encoding. Raises `ValueError` on NaN/Infinity."""
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        raise ValueError("preferences may only contain finite numbers") from exc
    return len(encoded.encode("utf-8"))


def _check_shape(value: object, limit: int) -> None:
    """Iterative walk: nesting depth ≤ `limit` (the top object is depth 1), no NUL in keys or strings."""
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            if depth > limit:
                raise ValueError(f"preferences nest deeper than {limit} levels")
            for key, child in node.items():
                if isinstance(key, str) and _NUL in key:
                    raise ValueError("preferences may not contain NUL characters")
                stack.append((child, depth + 1))
        elif isinstance(node, list):
            if depth > limit:
                raise ValueError(f"preferences nest deeper than {limit} levels")
            stack.extend((child, depth + 1) for child in node)
        elif isinstance(node, str) and _NUL in node:
            raise ValueError("preferences may not contain NUL characters")


def validate_preferences_patch(value: object) -> dict[str, Any]:
    """Check a request patch; returns a shallow copy. Raises `ValueError` (pydantic turns it into a 422)."""
    if not isinstance(value, dict):
        # ValueError on purpose: pydantic maps only ValueError to a validation error.
        raise ValueError("preferences must be an object")  # noqa: TRY004
    bad = sorted(k for k in value if not PREFERENCE_KEY_RE.fullmatch(k))
    if bad:
        raise ValueError(f"preference key {bad[0]!r} must match {PREFERENCE_KEY_RE.pattern}")
    if len(value) > MAX_PATCH_KEYS:
        raise ValueError(f"at most {MAX_PATCH_KEYS} preference keys per request")
    _check_shape(value, MAX_DEPTH)  # before the size check: json.dumps itself recurses
    if preferences_size(value) > MAX_PATCH_BYTES:
        raise ValueError(f"preferences patch exceeds {MAX_PATCH_BYTES} bytes")
    return dict(value)


def check_stored_preferences(merged: dict[str, Any]) -> None:
    """Check the post-merge object against the stored caps."""
    if len(merged) > MAX_STORED_KEYS:
        raise ValidationFailedError(f"at most {MAX_STORED_KEYS} preference keys may be stored")
    try:
        size = preferences_size(merged)
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    if size > MAX_STORED_BYTES:
        raise ValidationFailedError(f"stored preferences may not exceed {MAX_STORED_BYTES} bytes")
