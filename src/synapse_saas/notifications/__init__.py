"""Notifications: email seam, SMTP implementation, outbox event handlers."""

from __future__ import annotations

from typing import Protocol

from synapse_saas.notifications.smtp import SmtpNotifier, get_notifier


class Notifier(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class NoopNotifier:
    """Fallback: log only. Used implicitly when SYNAPSE_SMTP_HOST is unset."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        from synapse_saas.core.logging import get_logger

        get_logger(__name__).info("notification_suppressed", to=to, subject=subject)


__all__ = ["NoopNotifier", "Notifier", "SmtpNotifier", "get_notifier"]
