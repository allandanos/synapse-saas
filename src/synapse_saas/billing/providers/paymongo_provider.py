"""PayMongo provider (PH) — cards, GCash, Maya via Checkout Sessions.

Webhooks use the same t/v1 HMAC-SHA256 scheme as Stripe over the raw body.
Subscription-level recurring is thinner than Stripe's, so capability flags say
so and the framework scheduler fills the gap.

Interface-complete but less battle-tested than Stripe — see docs/billing-providers.md.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

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
from synapse_saas.core.errors import BillingProviderError, WebhookSignatureInvalidError
from synapse_saas.core.security import verify_signature

PAYMONGO_API_BASE = "https://api.paymongo.com/v1"
WEBHOOK_TOLERANCE_SECONDS = 300


class PayMongoBillingProvider(BillingProvider):
    name = "paymongo"
    supports = frozenset(
        {
            BillingCapability.HOSTED_CHECKOUT,
            BillingCapability.WEBHOOK_SIGNED,
        }
    )

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        secret_key: str,
        webhook_secret: str,
        api_base: str = PAYMONGO_API_BASE,
        currency: str = "PHP",
    ) -> None:
        self._http = http
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._api_base = api_base
        self._currency = currency

    async def _request(
        self, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        auth = base64.b64encode(f"{self._secret_key}:".encode()).decode()
        response = await self._http.request(
            method,
            f"{self._api_base}{path}",
            json=json_body,
            headers={"Authorization": f"Basic {auth}"},
        )
        if response.status_code >= 400:
            raise BillingProviderError(f"PayMongo API error: {response.text}")
        data: dict[str, Any] = response.json()
        return data

    async def create_customer(self, req: CreateCustomerRequest) -> BillingCustomerRef:
        # PayMongo has no first-class customer object; we mint a stable reference
        return BillingCustomerRef(
            provider_customer_id=f"paymongo_{secrets.token_hex(8)}",
            email=req.email,
            name=req.name,
        )

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResult:
        # PayMongo amounts are in minor units (centavos)
        result = await self._request(
            "POST",
            "/checkout_sessions",
            {
                "data": {
                    "attributes": {
                        "line_items": [
                            {
                                "name": req.plan_name,
                                "amount": req.price_cents,
                                "currency": req.currency,
                                "quantity": 1,
                            }
                        ],
                        "metadata": {"plan_key": req.plan_key, "org_id": str(req.organization_id or "")},
                    }
                }
            },
        )
        attributes = result["data"]["attributes"]
        return CheckoutResult(
            url=attributes.get("checkout_url"),
            provider=self.name,
            provider_checkout_id=result["data"]["id"],
        )

    async def create_subscription(self, req: CreateSubscriptionRequest) -> SubscriptionRef:
        return SubscriptionRef(
            provider_subscription_id=f"paymongosub_{secrets.token_hex(8)}",
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
        return []  # PayMongo surfaces payments, not invoices; we record locally

    async def verify_webhook(self, raw: WebhookRequest) -> VerifiedWebhook:
        """Paymongo-Signature: t=...,v1=... (same scheme as Stripe)."""
        header = raw.headers.get("paymongo-signature", "")
        timestamp: int | None = None
        signature: str | None = None
        for part in header.split(","):
            key, _, value = part.strip().partition("=")
            if key == "t":
                try:
                    timestamp = int(value)
                except ValueError:
                    timestamp = None
            elif key == "v1" and value:
                signature = value

        if timestamp is None or signature is None:
            raise WebhookSignatureInvalidError("Malformed Paymongo-Signature header")
        if abs(time.time() - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
            raise WebhookSignatureInvalidError("PayMongo webhook timestamp outside tolerance")
        if not verify_signature(raw.body, self._webhook_secret, timestamp=timestamp, signature=signature):
            raise WebhookSignatureInvalidError("PayMongo webhook signature mismatch")

        try:
            parsed = json.loads(raw.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookSignatureInvalidError("Malformed PayMongo webhook body") from exc

        attributes = parsed.get("data", {}).get("attributes", {})
        event_id = str(parsed.get("id") or f"paymongo_{secrets.token_hex(8)}")
        return VerifiedWebhook(
            provider_event_id=event_id,
            event_type=str(parsed.get("type", attributes.get("type", ""))),
            parsed=parsed,
            received_at=datetime.now(UTC),
        )

    def translate_webhook(self, verified: VerifiedWebhook) -> list[NormalizedBillingEvent]:
        data = verified.parsed.get("data", {})
        attributes = data.get("attributes", {})
        event_type = verified.event_type

        type_map = {
            "checkout_session.completed": NormalizedBillingEvent.CHECKOUT_COMPLETED,
            "payment.paid": NormalizedBillingEvent.INVOICE_PAID,
            "payment.failed": NormalizedBillingEvent.PAYMENT_FAILED,
        }
        canonical = type_map.get(event_type)
        if canonical is None:
            return []

        amount_cents = None
        for item in attributes.get("line_items") or []:
            if item.get("amount"):
                amount_cents = item["amount"]
                break
        if amount_cents is None and attributes.get("amount"):
            amount_cents = attributes["amount"]

        metadata = attributes.get("metadata") or {}
        return [
            NormalizedBillingEvent(
                event_type=canonical,
                provider_event_id=verified.provider_event_id,
                occurred_at=verified.received_at,
                plan_key=metadata.get("plan_key"),
                amount_cents=amount_cents,
                currency=metadata.get("currency", self._currency),
                raw=verified.parsed,
            )
        ]

    def _to_invoice_ref(self, data: dict[str, Any]) -> InvoiceRef:
        return InvoiceRef(
            provider_invoice_id=data.get("id", ""),
            number=None,
            status="paid",
            total_cents=int(data.get("amount", 0)),
            currency=self._currency,
        )
