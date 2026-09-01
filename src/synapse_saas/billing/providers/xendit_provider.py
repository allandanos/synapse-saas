"""Xendit provider (PH) — invoice-cycle based billing.

Xendit's recurring coverage works off scheduled invoices rather than a Stripe-
style subscription object, so capability flags report the difference and the
framework's manual billing scheduler fills the gap. Webhooks are authenticated
with a static `X-Callback-Token` compared in constant time.

Interface-complete but less battle-tested than Stripe — see docs/billing-providers.md.
"""

from __future__ import annotations

import base64
import json
import secrets
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
from synapse_saas.core.security import constant_time_equals

XENDIT_API_BASE = "https://api.xendit.co"


class XenditBillingProvider(BillingProvider):
    name = "xendit"
    supports = frozenset(
        {
            BillingCapability.HOSTED_CHECKOUT,
            BillingCapability.WEBHOOK_SIGNED,  # token-authenticated
        }
    )

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        secret_key: str,
        webhook_token: str,
        api_base: str = XENDIT_API_BASE,
        currency: str = "PHP",
    ) -> None:
        self._http = http
        self._secret_key = secret_key
        self._webhook_token = webhook_token
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
            raise BillingProviderError(f"Xendit API error: {response.text}")
        data: dict[str, Any] = response.json()
        return data

    async def create_customer(self, req: CreateCustomerRequest) -> BillingCustomerRef:
        result = await self._request(
            "POST",
            "/customers",
            {
                "reference_id": str(req.organization_id or secrets.token_hex(8)),
                "email": req.email,
                "given_names": req.name,
            },
        )
        return BillingCustomerRef(provider_customer_id=result["id"], email=req.email, name=req.name)

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResult:
        result = await self._request(
            "POST",
            "/invoices",
            {
                "external_id": f"synapse_{req.plan_key}_{secrets.token_hex(4)}",
                "amount": req.price_cents / 100,  # Xendit takes major units
                "currency": req.currency,
                "description": f"{req.plan_name} ({req.interval}ly)",
                "payer_email": None,
                "success_redirect_url": req.success_url,
                "failure_redirect_url": req.cancel_url,
            },
        )
        return CheckoutResult(
            url=result.get("invoice_url"),
            provider=self.name,
            provider_checkout_id=result.get("id"),
        )

    async def create_subscription(self, req: CreateSubscriptionRequest) -> SubscriptionRef:
        # Xendit recurring = scheduled invoice cycle; plan recurring is handled
        # by the framework's manual billing scheduler.
        return SubscriptionRef(
            provider_subscription_id=f"xenditsub_{secrets.token_hex(8)}",
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
        result = await self._request("GET", f"/v2/invoices?limit={limit}")
        return [self._to_invoice_ref(inv) for inv in result.get("data", [])]

    async def verify_webhook(self, raw: WebhookRequest) -> VerifiedWebhook:
        token = raw.headers.get("x-callback-token", "")
        if not self._webhook_token or not constant_time_equals(token, self._webhook_token):
            raise WebhookSignatureInvalidError("Missing or invalid X-Callback-Token")

        try:
            parsed = json.loads(raw.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookSignatureInvalidError("Malformed Xendit webhook body") from exc

        event_id = str(parsed.get("id") or f"xendit_{secrets.token_hex(8)}")
        return VerifiedWebhook(
            provider_event_id=event_id,
            event_type=str(parsed.get("status", "")),
            parsed=parsed,
            received_at=datetime.now(UTC),
        )

    def translate_webhook(self, verified: VerifiedWebhook) -> list[NormalizedBillingEvent]:
        status = verified.event_type
        data = verified.parsed

        type_map = {
            "PAID": NormalizedBillingEvent.INVOICE_PAID,
            "EXPIRED": NormalizedBillingEvent.INVOICE_FAILED,
        }
        canonical = type_map.get(status)
        if canonical is None:
            return []

        amount_cents = None
        if data.get("amount") is not None:
            amount_cents = int(float(data["amount"]) * 100)  # Xendit sends major units

        occurred = datetime.now(UTC)
        if data.get("created") and str(data["created"]).replace("-", "").isdigit():
            occurred = datetime.fromtimestamp(int(str(data["created"])[:10]), tz=UTC)

        return [
            NormalizedBillingEvent(
                event_type=canonical,
                provider_event_id=verified.provider_event_id,
                occurred_at=occurred,
                provider_invoice_id=data.get("id"),
                provider_customer_id=data.get("customer_id"),
                amount_cents=amount_cents,
                currency=data.get("currency", self._currency),
                hosted_url=data.get("invoice_url"),
                raw=verified.parsed,
            )
        ]

    def _to_invoice_ref(self, data: dict[str, Any]) -> InvoiceRef:
        return InvoiceRef(
            provider_invoice_id=data.get("id", ""),
            number=data.get("external_id"),
            status="paid" if data.get("status") == "PAID" else "open",
            total_cents=int(float(data.get("amount", 0)) * 100),
            currency=data.get("currency", self._currency),
            hosted_url=data.get("invoice_url"),
        )
