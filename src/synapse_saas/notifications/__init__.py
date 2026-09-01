"""Notifications seam (Phase 3). Interface + no-op so consumers can be written today."""

from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class NoopNotifier:
    """Default: log only. Swap for email/push implementations in Phase 3."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        from synapse_saas.core.logging import get_logger

        get_logger(__name__).info("notification_suppressed", to=to, subject=subject)
