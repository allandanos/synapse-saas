"""Notifications: email seam, SMTP implementation, outbox event handlers.

`Notifier` is the transport seam: SMTP (with AUTH/STARTTLS/SSL) or Noop, chosen
by `get_notifier()` from SYNAPSE_NOTIFIER + SYNAPSE_SMTP_HOST. Swap the
transport by binding a different implementation — the protocol carries
attachments (invoice PDFs) so any transport can honour them.
"""

from __future__ import annotations

from typing import Protocol

from synapse_saas.notifications.smtp import Attachment, NoopNotifier, SmtpNotifier, get_notifier


class Notifier(Protocol):
    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Attachment] | None = None,
    ) -> None: ...


__all__ = ["Attachment", "NoopNotifier", "Notifier", "SmtpNotifier", "get_notifier"]
