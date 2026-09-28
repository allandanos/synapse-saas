"""SMTP notifier — sends through the configured relay, fails soft.

stdlib smtplib wrapped in asyncio.to_thread: no new dependency, and SMTP is
inherently blocking. Delivery failure logs and swallows — an email must never
fail the outbox dispatch that carries it.
"""

from __future__ import annotations

import contextlib
import smtplib
from email.message import EmailMessage
from typing import TYPE_CHECKING

from synapse_saas.core.config import get_settings
from synapse_saas.core.logging import get_logger

if TYPE_CHECKING:
    from synapse_saas.notifications import Notifier

logger = get_logger(__name__)


class Attachment:
    """A named binary attachment (invoice PDFs)."""

    def __init__(self, filename: str, content: bytes, content_type: str) -> None:
        self.filename = filename
        self.content = content
        self.content_type = content_type


class SmtpNotifier:
    """Sends when SYNAPSE_SMTP_HOST is set; Noop semantics otherwise."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Attachment] | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            logger.info(
                "notification_suppressed_no_smtp",
                to=to,
                subject=subject,
                attachments=len(attachments or []),
            )
            _inc_email("suppressed")
            return
        try:
            message = EmailMessage()
            message["From"] = settings.smtp_from
            message["To"] = to
            message["Subject"] = subject
            message.set_content(body)
            for attachment in attachments or []:
                maintype, _, subtype = attachment.content_type.partition("/")
                message.add_attachment(
                    attachment.content,
                    maintype=maintype,
                    subtype=subtype,
                    filename=attachment.filename,
                )
            await _send_message(
                message,
                settings.smtp_host,
                settings.smtp_port,
                tls=settings.smtp_tls,
                username=settings.smtp_username,
                password=settings.smtp_password,
            )
            logger.info("email_sent", to=to, subject=subject, attachments=len(attachments or []))
            _inc_email("sent")
        except Exception as exc:
            logger.warning("email_send_failed", to=to, subject=subject, error=str(exc))
            _inc_email("failed")


async def _send_message(
    message: EmailMessage,
    host: str,
    port: int,
    *,
    tls: str = "none",
    username: str = "",
    password: str = "",
) -> None:
    """Deliver over SMTP with the configured transport security and AUTH.

    - ssl: implicit TLS from the first byte (port 465)
    - starttls: plaintext hello, then STARTTLS (port 587)
    - none: plaintext (MailHog / a trusted relay on localhost)
    Credentials are sent only after the channel is secured — never in the clear.
    """
    import asyncio
    import ssl

    def _deliver() -> None:
        if tls == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=10, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(host, port, timeout=10)
        with client as smtp:
            if tls == "starttls":
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if username:
                if tls == "none":
                    raise RuntimeError(
                        "SMTP AUTH over a plaintext connection is refused; set SYNAPSE_SMTP_TLS"
                    )
                smtp.login(username, password)
            smtp.send_message(message)

    await asyncio.to_thread(_deliver)


def get_notifier() -> Notifier:
    """The configured transport: SMTP when a host is set (and not forced to noop), else Noop."""
    settings = get_settings()
    if settings.notifier == "noop" or not settings.smtp_host:
        return NoopNotifier()
    return SmtpNotifier()


class NoopNotifier:
    """Log-only transport: what runs when no SMTP host is configured."""

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Attachment] | None = None,
    ) -> None:
        logger.info("notification_suppressed", to=to, subject=subject, attachments=len(attachments or []))
        _inc_email("suppressed")


def _inc_email(outcome: str) -> None:
    with contextlib.suppress(Exception):  # metrics must never fail email dispatch
        from synapse_saas.core import metrics

        metrics.EMAILS.labels(outcome=outcome).inc()
