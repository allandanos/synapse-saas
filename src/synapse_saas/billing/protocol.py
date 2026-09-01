"""BillingProvider protocol — the abstraction that keeps the framework
provider-agnostic.

Webhook handling is split into two methods on purpose:
- `verify_webhook(raw)` — signature/timestamp verification over raw bytes + headers
- `translate_webhook(verified)` — parsed JSON → NormalizedBillingEvent list

Verification is transport security; translation is schema mapping. Providers
with exotic verification (Xendit's static token vs Stripe's HMAC) differ only
in the first half.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID


class BillingCapability(StrEnum):
    HOSTED_CHECKOUT = "hosted_checkout"
    BILLING_PORTAL = "billing_portal"
    RECURRING_HOSTED = "recurring_hosted"  # provider-side recurring subscriptions
    PLAN_SYNC = "plan_sync"  # can push our catalog to the provider
    WEBHOOK_SIGNED = "webhook_signed"


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """Raw webhook material. Body is the exact bytes the provider signed."""

    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class VerifiedWebhook:
    provider_event_id: str
    event_type: str
    parsed: dict[str, Any]
    received_at: datetime


@dataclass(frozen=True, slots=True)
class NormalizedBillingEvent:
    """Canonical, provider-agnostic billing event."""

    event_type: str  # subscription.activated | invoice.paid | ...
    provider_event_id: str
    occurred_at: datetime
    provider_customer_id: str | None = None
    provider_subscription_id: str | None = None
    provider_invoice_id: str | None = None
    plan_key: str | None = None
    status: str | None = None
    current_period_end: datetime | None = None
    amount_cents: int | None = None
    currency: str | None = None
    hosted_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # Canonical event vocabulary
    CUSTOMER_CREATED = "customer.created"
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_ACTIVATED = "subscription.activated"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    SUBSCRIPTION_PAST_DUE = "subscription.past_due"
    SUBSCRIPTION_TRIAL_ENDED = "subscription.trial_ended"
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    INVOICE_FAILED = "invoice.failed"
    CHECKOUT_COMPLETED = "checkout.completed"
    PAYMENT_FAILED = "payment.failed"


@dataclass(frozen=True, slots=True)
class BillingCustomerRef:
    provider_customer_id: str
    email: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    """Hosted-checkout URL, or manual instructions for off-provider flows."""

    url: str | None
    provider: str
    manual_instructions: str | None = None
    provider_checkout_id: str | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionRef:
    provider_subscription_id: str
    status: str
    current_period_end: datetime | None = None
    provider_customer_id: str | None = None


@dataclass(frozen=True, slots=True)
class InvoiceRef:
    provider_invoice_id: str
    number: str | None
    status: str
    total_cents: int
    currency: str
    hosted_url: str | None = None
    pdf_url: str | None = None
    issued_at: datetime | None = None
    paid_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None


# ── Requests ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CreateCustomerRequest:
    email: str
    name: str | None = None
    organization_id: UUID | None = None
    currency: str = "PHP"


@dataclass(frozen=True, slots=True)
class CreateCheckoutRequest:
    plan_key: str
    plan_name: str
    price_cents: int
    currency: str
    interval: str
    provider_customer_id: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    organization_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateSubscriptionRequest:
    plan_key: str
    price_cents: int
    currency: str
    interval: str
    provider_customer_id: str
    trial_days: int = 0


@dataclass(frozen=True, slots=True)
class ChangePlanRequest:
    plan_key: str
    price_cents: int
    currency: str
    interval: str


class BillingProvider(ABC):
    """Every provider implements this. Built on raw httpx — no vendor SDKs."""

    name: ClassVar[str]
    supports: ClassVar[frozenset[BillingCapability]]

    @abstractmethod
    async def create_customer(self, req: CreateCustomerRequest) -> BillingCustomerRef: ...

    @abstractmethod
    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResult: ...

    async def billing_portal_url(self, provider_customer_id: str, *, return_url: str) -> str:
        raise NotImplementedError(f"{self.name} does not support billing portals")

    @abstractmethod
    async def create_subscription(self, req: CreateSubscriptionRequest) -> SubscriptionRef: ...

    @abstractmethod
    async def change_plan(self, provider_subscription_id: str, req: ChangePlanRequest) -> SubscriptionRef: ...

    @abstractmethod
    async def cancel_subscription(
        self, provider_subscription_id: str, *, at_period_end: bool = True
    ) -> SubscriptionRef: ...

    @abstractmethod
    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionRef: ...

    @abstractmethod
    async def list_invoices(self, provider_customer_id: str, *, limit: int = 20) -> list[InvoiceRef]: ...

    @abstractmethod
    async def verify_webhook(self, raw: WebhookRequest) -> VerifiedWebhook: ...

    @abstractmethod
    def translate_webhook(self, verified: VerifiedWebhook) -> list[NormalizedBillingEvent]: ...
