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

    elif event_type == "usage.soft_limit_reached":
        # Org-level warning: routed to the billing-contact email when known
        metric = payload.get("metric")
        org_id = payload.get("organization_id")
        logger.info("soft_limit_email", metric=metric, org=str(org_id))
        # Recipient resolution (org billing contact) is a later refinement;
        # the event still lands in audit + webhooks today.

    # Other events intentionally unhandled — email is opt-in per event type.
