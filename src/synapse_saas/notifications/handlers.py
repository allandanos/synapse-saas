"""Email templates + outbox event → email mapping.

The worker's outbox dispatch invokes `handle_event` for user-facing events.
Every handler is best-effort: an email problem must never fail the dispatch.
"""

from __future__ import annotations

from typing import Any

from synapse_saas.core.config import get_settings
from synapse_saas.core.logging import get_logger
from synapse_saas.notifications.smtp import get_notifier

logger = get_logger(__name__)


def _web_url(path: str = "") -> str:
    settings = get_settings()
    base = settings.web_origin.rstrip("/")
    return f"{base}{path}"


async def handle_event(event_type: str, payload: dict[str, Any]) -> None:
    """Map one outbox event to at most one email. Unknown events are ignored."""
    notifier = get_notifier()

    if event_type == "member.invited":
        email = payload.get("email")
        token = payload.get("invite_token")
        org = payload.get("org_name", "an organization")
        if not email or not token:
            logger.debug("invite_email_skipped", reason="missing fields")
            return
        # The console accepts invite tokens on registration
        link = _web_url(f"/register?invite={token}")
        await notifier.send(
            to=str(email),
            subject=f"You've been invited to {org}",
            body=(
                f"Someone invited you to {org}.\n\n"
                f"Accept your invitation by registering with this link:\n{link}\n\n"
                "If you weren't expecting this, you can ignore this email."
            ),
        )

    elif event_type == "user.password_reset_link":
        email = payload.get("email")
        token = payload.get("token")
        if not email or not token:
            return
        link = _web_url(f"/login?reset={token}")  # console routes to reset form
        await notifier.send(
            to=str(email),
            subject="Reset your password",
            body=(
                "A password reset was requested for your account.\n\n"
                f"Reset it here (valid 30 minutes):\n{link}\n\n"
                "If you didn't request this, ignore this email."
            ),
        )

    elif event_type == "invoice.email":
        # Invoice delivery: finalize/pay hooks queue {invoice_id} with the
        # rendered-PDF path; the PDF is regenerated at send time so the
        # attachment always matches current invoice state.
        invoice_id = payload.get("invoice_id")
        if not invoice_id:
            logger.debug("invoice_email_skipped", reason="missing invoice_id")
            return
        await _send_invoice_email(str(invoice_id))

    elif event_type == "usage.soft_limit_reached":
        # Org-level warning: routed to the billing-contact email when known
        metric = payload.get("metric")
        org_id = payload.get("organization_id")
        logger.info("soft_limit_email", metric=metric, org=str(org_id))
        # Recipient resolution (org billing contact) is a later refinement;
        # the event still lands in audit + webhooks today.

    # Other events intentionally unhandled — email is opt-in per event type.


async def _send_invoice_email(invoice_id: str) -> None:
    """Render the invoice PDF + compose and send the delivery email.

    Runs inside the worker's outbox dispatch: DB access is synchronous-safe
    here (same process pool), failures log-and-continue per the notifer contract.
    """
    import asyncio

    from sqlalchemy import select

    from synapse_saas.billing.invoice_pdf import render_invoice_pdf
    from synapse_saas.billing.invoicing import InvoiceLine
    from synapse_saas.billing.models import BillingCustomer, Invoice
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.notifications.smtp import Attachment
    from synapse_saas.tenancy.models import Organization

    async def _compose() -> tuple[str, str, Attachment, str] | None:
        factory = get_session_factory()
        async with factory() as session:
            invoice = (
                await session.execute(select(Invoice).where(Invoice.id == invoice_id))
            ).scalar_one_or_none()
            if invoice is None:
                logger.warning("invoice_email_invoice_missing", invoice_id=invoice_id)
                return None
            lines = list(
                (await session.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)))
                .scalars()
                .all()
            )
            org = await session.get(Organization, invoice.organization_id)
            org_name = org.name if org else "Customer"
            org_settings = org.settings if org else {}

            billing_email: str | None = None
            if invoice.billing_customer_id is not None:
                customer = await session.get(BillingCustomer, invoice.billing_customer_id)
                billing_email = str(customer.email) if customer and customer.email else None
            settings_recipient = org_settings.get("billing_email")
            recipient = billing_email or (settings_recipient if isinstance(settings_recipient, str) else None)
            if not recipient or not isinstance(recipient, str):
                logger.info("invoice_email_no_recipient", invoice_id=invoice_id)
                return None

            pdf_bytes = await asyncio.to_thread(
                render_invoice_pdf,
                invoice,
                lines,
                org_name=org_name,
                billing_email=billing_email,
                pay_to_instructions=_pay_to(),
            )
            number = invoice.number or str(invoice.id)
            total = f"{invoice.total_cents / 100:,.2f} {invoice.currency}"
            if invoice.status == "paid":
                subject = f"Paid: Invoice {number}"
                body = (
                    f"Your payment for invoice {number} ({total}) has been received. "
                    "The invoice is attached for your records."
                )
            else:
                subject = f"Invoice {number}: {total} due"
                body = (
                    f"Invoice {number} for {total} is attached. Payment instructions are included in the PDF."
                )
            attachment = Attachment(
                filename=f"invoice-{number}.pdf",
                content=pdf_bytes,
                content_type="application/pdf",
            )
            return subject, body, attachment, recipient

    composed = await _compose()
    if composed is None:
        return
    subject, body, attachment, recipient = composed
    await get_notifier().send(
        to=recipient,
        subject=subject,
        body=body,
        attachments=[attachment] if attachment else None,
    )


def _pay_to() -> str | None:
    from synapse_saas.core.config import get_settings

    instructions = get_settings().manual_pay_to_instructions
    return instructions or None
