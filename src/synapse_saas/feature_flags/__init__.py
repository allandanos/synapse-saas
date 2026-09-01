"""Feature flags seam (Phase 3). Interface only.

Entitlements already cover plan-based gating; flags add org/user overrides
independent of billing when Phase 3 lands."""

from __future__ import annotations

from typing import Protocol


class FeatureFlagService(Protocol):
    async def is_enabled(self, *, key: str, organization_id: str | None = None) -> bool: ...
