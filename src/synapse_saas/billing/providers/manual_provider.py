"""Manual / Enterprise billing provider.

Zero external accounts — the default so `docker compose up` gives you the full
freemium loop locally. "Checkout" is an internal confirmation page; renewals
are advanced by the worker's `advance_manual_billing` job which issues invoices
on period roll. For enterprise contracts, an operator applies plan changes and
invoices are recorded manually.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from synapse_saas.billing.protocol import (
    BillingCapability,
    BillingCustomerRef,
    BillingProvider,
    ChangePlanRequest,
    CheckoutResult,
    CreateCheckoutRequest,
    CreateCustomerRequest,
    CreateSubscriptionRequest,
    InvoiceRef,
    NormalizedBillingEvent,
    SubscriptionRef,
    VerifiedWebhook,
    WebhookRequest,
)
from synapse_saas.core.errors import WebhookSignatureInvalidError


class ManualBillingProvider(BillingProvider):
    name = "manual"
    supports = frozenset({BillingCapability.HOSTED_CHECKOUT})  # "hosted" = internal page

    def __init__(self, webhook_token: str = "", currency: str = "PHP") -> None:
        self._webhook_token = webhook_token
        self._currency = currency

    async def create_customer(self, req: CreateCustomerRequest) -> BillingCustomerRef:
        return BillingCustomerRef(
            provider_customer_id=f"manual_{secrets.token_hex(8)}",
            email=req.email,
            name=req.name,
        )

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResult:
        # Manual checkout renders our own confirmation page; no external URL.
        return CheckoutResult(
            url=None,
            provider=self.name,
            provider_checkout_id=f"manualco_{secrets.token_hex(8)}",
            manual_instructions=(
                f"Confirm the {req.plan_name} plan "
                f"({_format_money(req.price_cents, req.currency)}/{req.interval}). "
                "No payment provider is configured; the subscription activates immediately "
                "and invoices are recorded by the system."
            ),
        )

    async def create_subscription(self, req: CreateSubscriptionRequest) -> SubscriptionRef:
        return SubscriptionRef(
            provider_subscription_id=f"manualsub_{secrets.token_hex(8)}",
            status="active",
            current_period_end=datetime.now(UTC) + timedelta(days=30),
            provider_customer_id=req.provider_customer_id,
        )

    async def change_plan(self, provider_subscription_id: str, req: ChangePlanRequest) -> SubscriptionRef:
        return SubscriptionRef(
            provider_subscription_id=provider_subscription_id,
            status="active",
            current_period_end=datetime.now(UTC) + timedelta(days=30),
        )

    async def cancel_subscription(
        self, provider_subscription_id: str, *, at_period_end: bool = True
    ) -> SubscriptionRef:
        return SubscriptionRef(
            provider_subscription_id=provider_subscription_id,
            status="canceled",
        )

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionRef:
        return SubscriptionRef(
            provider_subscription_id=provider_subscription_id,
            status="active",
            current_period_end=datetime.now(UTC) + timedelta(days=30),
        )

    async def list_invoices(self, provider_customer_id: str, *, limit: int = 20) -> list[InvoiceRef]:
        return []  # manual invoices live in our DB only

    async def verify_webhook(self, raw: WebhookRequest) -> VerifiedWebhook:
        """Manual webhook ingest is protected by a shared deployment token."""
        token = raw.headers.get("x-manual-token", "")
        from synapse_saas.core.security import constant_time_equals

        if not self._webhook_token or not constant_time_equals(token, self._webhook_token):
            raise WebhookSignatureInvalidError("Missing or invalid manual webhook token")

        import json

        try:
            parsed = json.loads(raw.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookSignatureInvalidError("Malformed manual webhook body") from exc

        event_id = str(parsed.get("id") or f"manual_{secrets.token_hex(8)}")
        return VerifiedWebhook(
            provider_event_id=event_id,
            event_type=str(parsed.get("type", "manual.event")),
            parsed=parsed,
            received_at=datetime.now(UTC),
        )

    def translate_webhook(self, verified: VerifiedWebhook) -> list[NormalizedBillingEvent]:
        event_type = verified.parsed.get("type", "")
        mapping = {
            "manual.subscription.activated": NormalizedBillingEvent.SUBSCRIPTION_ACTIVATED,
            "manual.subscription.canceled": NormalizedBillingEvent.SUBSCRIPTION_CANCELED,
            "manual.invoice.paid": NormalizedBillingEvent.INVOICE_PAID,
        }
        canonical = mapping.get(event_type)
        if canonical is None:
            return []
        data = verified.parsed.get("data", {})
        return [
            NormalizedBillingEvent(
                event_type=canonical,
                provider_event_id=verified.provider_event_id,
                occurred_at=verified.received_at,
                provider_subscription_id=data.get("subscription_id"),
                provider_customer_id=data.get("customer_id"),
                plan_key=data.get("plan_key"),
                status=data.get("status"),
                amount_cents=data.get("amount_cents"),
                currency=data.get("currency"),
                raw=verified.parsed,
            )
        ]


def _format_money(cents: int, currency: str) -> str:
    symbols = {"PHP": "₱", "USD": "$", "EUR": "€"}
    symbol = symbols.get(currency, f"{currency} ")
    return f"{symbol}{cents / 100:,.2f}"
