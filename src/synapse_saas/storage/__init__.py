"""Storage seam (Phase 3). Interface only — S3-compatible when implemented."""

from __future__ import annotations

from typing import Protocol


class Storage(Protocol):
    async def put(self, *, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, *, key: str) -> bytes: ...
    async def delete(self, *, key: str) -> None: ...
