"""ID generation and slug utilities.

UUIDv7 (time-ordered) for high-volume rows so B-tree locality matches insert order —
usage events, outbox events, deliveries, audit logs. UUIDv4 for low-volume entities.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from datetime import UTC, datetime

_SLUG_RE = re.compile(r"[^a-z0-9]+")
RESERVED_SLUGS = frozenset(
    {
        "www",
        "api",
        "app",
        "admin",
        "mail",
        "smtp",
        "ftp",
        "sftp",
        "ssh",
        "support",
        "help",
        "billing",
        "checkout",
        "pay",
        "login",
        "signin",
        "signup",
        "register",
        "logout",
        "static",
        "assets",
        "cdn",
        "docs",
        "status",
        "health",
        "platform",
        "system",
        "root",
        "synapse",
        "dashboard",
        "console",
        "portal",
    }
)


def uuid_v7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit unix-ms timestamp + random, fully unguessable beyond the timestamp."""
    ts_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF  # 12 bits, version goes on top
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF  # 62 bits

    value = (ts_ms & 0xFFFFFFFFFFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= rand_a << 64
    value |= 0b10 << 62  # RFC variant
    value |= rand_b
    return uuid.UUID(int=value)


def new_uuid() -> uuid.UUID:
    """Standard UUIDv4 for low-volume entities."""
    return uuid.uuid4()


def uuid_v7_timestamp(value: uuid.UUID) -> datetime:
    """Extract the embedded creation time from a UUIDv7 (useful for debugging/diffing)."""
    ms = value.int >> 80
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def slugify(text: str, *, max_length: int = 48) -> str:
    """Lowercase [a-z0-9-] slug, collapsed separators, trimmed, length-capped."""
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:max_length].strip("-")
    return slug


def is_valid_slug(slug: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,46}[a-z0-9])?", slug)) and slug not in RESERVED_SLUGS


def unique_slug(base: str) -> str:
    """Slug with a short random suffix — used when the preferred slug is taken."""
    suffix = os.urandom(3).hex()
    stem = slugify(base)[:39].strip("-") or "org"
    return f"{stem}-{suffix}"
