"""SMTP notifier — sends through the configured relay, fails soft.

stdlib smtplib wrapped in asyncio.to_thread: no new dependency, and SMTP is
inherently blocking. Delivery failure logs and swallows — an email must never
fail the outbox dispatch that carries it.
"""

from __future__ import annotations

import contextlib
import smtplib
from email.message import EmailMessage

from synapse_saas.core.config import get_settings
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)


class SmtpNotifier:
    """Sends when SYNAPSE_SMTP_HOST is set; Noop semantics otherwise."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            logger.info("notification_suppressed_no_smtp", to=to, subject=subject)
            _inc_email("suppressed")
            return
        try:
            message = EmailMessage()
            message["From"] = settings.smtp_from
            message["To"] = to
            message["Subject"] = subject
            message.set_content(body)
            await _send_message(message, settings.smtp_host, settings.smtp_port)
            logger.info("email_sent", to=to, subject=subject)
        except Exception as exc:
            logger.warning("email_send_failed", to=to, subject=subject, error=str(exc))


async def _send_message(message: EmailMessage, host: str, port: int) -> None:
    import asyncio

    def _deliver() -> None:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.send_message(message)

    await asyncio.to_thread(_deliver)


def get_notifier() -> SmtpNotifier:
    return SmtpNotifier()


def _inc_email(outcome: str) -> None:
    with contextlib.suppress(Exception):  # metrics must never fail email dispatch
        from synapse_saas.core import metrics

        metrics.EMAILS.labels(outcome=outcome).inc()
