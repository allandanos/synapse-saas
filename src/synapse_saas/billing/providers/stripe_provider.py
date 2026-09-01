"""Stripe provider — full integration over raw httpx.

No stripe SDK: keeps all providers uniform and signature verification
testable with respx. Endpoints, form encoding, and webhook scheme follow
Stripe's public API exactly.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
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

STRIPE_API_BASE = "https://api.stripe.com/v1"
WEBHOOK_TOLERANCE_SECONDS = 300


class StripeBillingProvider(BillingProvider):
    name = "stripe"
    supports = frozenset(
        {
            BillingCapability.HOSTED_CHECKOUT,
            BillingCapability.BILLING_PORTAL,
            BillingCapability.RECURRING_HOSTED,
            BillingCapability.PLAN_SYNC,
            BillingCapability.WEBHOOK_SIGNED,
        }
    )

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        secret_key: str,
        webhook_secret: str,
        api_base: str = STRIPE_API_BASE,
        currency: str = "PHP",
    ) -> None:
        self._http = http
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._api_base = api_base
        self._currency = currency

    # ── HTTP helpers ────────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._http.request(
            method,
            f"{self._api_base}{path}",
            data=self._flatten(data or {}),
            auth=(self._secret_key, ""),
        )
        if response.status_code >= 400:
            detail = response.json().get("error", {}).get("message", response.text)
            raise BillingProviderError(f"Stripe API error: {detail}")
        return response.json()

    @staticmethod
    def _flatten(data: dict[str, Any], *, prefix: str = "") -> dict[str, str]:
        """Stripe expects form-encoded nested params: price_data[currency]=PHP."""
        flat: dict[str, str] = {}
        for key, value in data.items():
            full = f"{prefix}[{key}]" if prefix else key
            if isinstance(value, dict):
                flat.update(StripeBillingProvider._flatten(value, prefix=full))
            elif isinstance(value, bool):
                flat[full] = "true" if value else "false"
            elif value is not None:
                flat[full] = str(value)
        return flat

    # ── Customers / checkout ────────────────────────────────────────────────────

    async def create_customer(self, req: CreateCustomerRequest) -> BillingCustomerRef:
        result = await self._request(
            "POST",
            "/customers",
            {"email": req.email, "name": req.name, "metadata[org]": str(req.organization_id or "")},
        )
        return BillingCustomerRef(provider_customer_id=result["id"], email=req.email, name=req.name)

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResult:
        data: dict[str, Any] = {
            "mode": "subscription",
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": req.currency.lower(),
            "line_items[0][price_data][unit_amount]": req.price_cents,
            "line_items[0][price_data][recurring][interval]": req.interval,
            "line_items[0][price_data][product_data][name]": req.plan_name,
            "metadata[plan_key]": req.plan_key,
            "metadata[org_id]": str(req.organization_id or ""),
        }
        if req.provider_customer_id:
            data["customer"] = req.provider_customer_id
        if req.success_url:
            data["success_url"] = req.success_url
        if req.cancel_url:
            data["cancel_url"] = req.cancel_url

        result = await self._request("POST", "/checkout/sessions", data)
        return CheckoutResult(
            url=result.get("url"),
            provider=self.name,
            provider_checkout_id=result["id"],
        )

    async def billing_portal_url(self, provider_customer_id: str, *, return_url: str) -> str:
        result = await self._request(
            "POST",
            "/billing_portal/sessions",
            {"customer": provider_customer_id, "return_url": return_url},
        )
        return str(result["url"])

    # ── Subscriptions ───────────────────────────────────────────────────────────

    async def create_subscription(self, req: CreateSubscriptionRequest) -> SubscriptionRef:
        data: dict[str, Any] = {
            "customer": req.provider_customer_id,
            "items[0][price_data][currency]": req.currency.lower(),
            "items[0][price_data][unit_amount]": req.price_cents,
            "items[0][price_data][recurring][interval]": req.interval,
            "items[0][price_data][product_data][name]": req.plan_key,
            "metadata[plan_key]": req.plan_key,
        }
        if req.trial_days:
            data["trial_period_days"] = req.trial_days
        result = await self._request("POST", "/subscriptions", data)
        return self._to_subscription_ref(result)

    async def change_plan(self, provider_subscription_id: str, req: ChangePlanRequest) -> SubscriptionRef:
        current = await self._request("GET", f"/subscriptions/{provider_subscription_id}")
        item_id = current["items"]["data"][0]["id"]
        result = await self._request(
            "POST",
            f"/subscriptions/{provider_subscription_id}",
            {
                "items[0][id]": item_id,
                "items[0][price_data][currency]": req.currency.lower(),
                "items[0][price_data][unit_amount]": req.price_cents,
                "items[0][price_data][recurring][interval]": req.interval,
                "metadata[plan_key]": req.plan_key,
            },
        )
        return self._to_subscription_ref(result)

    async def cancel_subscription(
        self, provider_subscription_id: str, *, at_period_end: bool = True
    ) -> SubscriptionRef:
        if at_period_end:
            # POST with the flag in the form body; Stripe ignores query params here
            result = await self._request(
                "POST",
                f"/subscriptions/{provider_subscription_id}",
                {"cancel_at_period_end": True},
            )
        else:
            result = await self._request("DELETE", f"/subscriptions/{provider_subscription_id}")
        return self._to_subscription_ref(result)

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionRef:
        result = await self._request("GET", f"/subscriptions/{provider_subscription_id}")
        return self._to_subscription_ref(result)

    async def list_invoices(self, provider_customer_id: str, *, limit: int = 20) -> list[InvoiceRef]:
        result = await self._request("GET", f"/invoices?customer={provider_customer_id}&limit={limit}")
        return [self._to_invoice_ref(inv) for inv in result.get("data", [])]

    # ── Webhooks ────────────────────────────────────────────────────────────────

    async def verify_webhook(self, raw: WebhookRequest) -> VerifiedWebhook:
        signature_header = raw.headers.get("stripe-signature", "")
        timestamp, signature = _parse_stripe_signature(signature_header)
        if timestamp is None or signature is None:
            raise WebhookSignatureInvalidError("Malformed Stripe-Signature header")

        if abs(time.time() - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
            raise WebhookSignatureInvalidError("Stripe webhook timestamp outside tolerance window")

        if not verify_signature(raw.body, self._webhook_secret, timestamp=timestamp, signature=signature):
            raise WebhookSignatureInvalidError("Stripe webhook signature mismatch")

        try:
            parsed = json.loads(raw.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookSignatureInvalidError("Malformed Stripe webhook body") from exc

        return VerifiedWebhook(
            provider_event_id=str(parsed.get("id", "")),
            event_type=str(parsed.get("type", "")),
            parsed=parsed,
            received_at=datetime.now(UTC),
        )

    def translate_webhook(self, verified: VerifiedWebhook) -> list[NormalizedBillingEvent]:
        event_type = verified.event_type
        data = verified.parsed.get("data", {}).get("object", {})
        occurred_at = datetime.fromtimestamp(verified.parsed.get("created", int(time.time())), tz=UTC)

        type_map = {
            "customer.subscription.created": NormalizedBillingEvent.SUBSCRIPTION_CREATED,
            "customer.subscription.updated": NormalizedBillingEvent.SUBSCRIPTION_UPDATED,
            "customer.subscription.deleted": NormalizedBillingEvent.SUBSCRIPTION_CANCELED,
            "invoice.paid": NormalizedBillingEvent.INVOICE_PAID,
            "invoice.payment_failed": NormalizedBillingEvent.INVOICE_FAILED,
            "checkout.session.completed": NormalizedBillingEvent.CHECKOUT_COMPLETED,
        }
        canonical = type_map.get(event_type)
        if canonical is None:
            return []

        status_map = {
            "trialing": "trialing",
            "active": "active",
            "past_due": "past_due",
            "canceled": "canceled",
            "unpaid": "unpaid",
            "incomplete": "incomplete",
        }

        period_end = None
        if isinstance(data.get("current_period_end"), int):
            period_end = datetime.fromtimestamp(data["current_period_end"], tz=UTC)

        return [
            NormalizedBillingEvent(
                event_type=canonical,
                provider_event_id=verified.provider_event_id,
                occurred_at=occurred_at,
                provider_customer_id=data.get("customer"),
                provider_subscription_id=data.get("id")
                if "subscription" in event_type
                else data.get("subscription"),
                provider_invoice_id=data.get("id") if "invoice" in event_type else None,
                plan_key=(data.get("metadata") or {}).get("plan_key"),
                status=status_map.get(data.get("status", "")),
                current_period_end=period_end,
                amount_cents=data.get("amount_paid") or data.get("amount_due"),
                currency=(data.get("currency") or "").upper() or None,
                hosted_url=data.get("hosted_invoice_url"),
                raw=verified.parsed,
            )
        ]

    # ── Plan sync (CLI) ─────────────────────────────────────────────────────────

    async def upsert_product_and_price(
        self, *, plan_key: str, plan_name: str, price_cents: int, currency: str, interval: str
    ) -> dict[str, str]:
        """Create (or reuse) a product+price for a plan. Returns ids for provider_refs."""
        product = await self._request(
            "POST", "/products", {"name": plan_name, "metadata[plan_key]": plan_key}
        )
        price = await self._request(
            "POST",
            "/prices",
            {
                "product": product["id"],
                "currency": currency.lower(),
                "unit_amount": price_cents,
                "recurring[interval]": interval,
            },
        )
        return {"product_id": product["id"], "price_id": price["id"]}

    # ── Internals ───────────────────────────────────────────────────────────────

    def _to_subscription_ref(self, data: dict[str, Any]) -> SubscriptionRef:
        period_end = None
        if isinstance(data.get("current_period_end"), int):
            period_end = datetime.fromtimestamp(data["current_period_end"], tz=UTC)
        return SubscriptionRef(
            provider_subscription_id=data["id"],
            status=data.get("status", "active"),
            current_period_end=period_end,
            provider_customer_id=data.get("customer"),
        )

    def _to_invoice_ref(self, data: dict[str, Any]) -> InvoiceRef:
        return InvoiceRef(
            provider_invoice_id=data["id"],
            number=data.get("number"),
            status=data.get("status", "open"),
            total_cents=data.get("total", 0),
            currency=(data.get("currency") or "PHP").upper(),
            hosted_url=data.get("hosted_invoice_url"),
            pdf_url=data.get("invoice_pdf"),
            issued_at=datetime.fromtimestamp(data["created"], tz=UTC) if data.get("created") else None,
            paid_at=datetime.fromtimestamp(data["status_transitions"]["paid_at"], tz=UTC)
            if data.get("status_transitions", {}).get("paid_at")
            else None,
        )


def _parse_stripe_signature(header: str) -> tuple[int | None, str | None]:
    """Stripe-Signature: t=1234567890,v1=abc123 — v1 may repeat; any match wins."""
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return None, None
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        return None, None
    return timestamp, signatures[0]
