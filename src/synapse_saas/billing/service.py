"""Billing domain service.

Customer management, checkout, plan changes through the active provider.
Provider calls happen BEFORE the DB mutation so a failed provider call leaves
no local state behind.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.billing.models import BillingCustomer, Invoice
from synapse_saas.billing.protocol import (
    BillingCapability,
    BillingProvider,
    ChangePlanRequest,
    CheckoutResult,
    CreateCheckoutRequest,
    CreateCustomerRequest,
)
from synapse_saas.billing.registry import build_provider
from synapse_saas.core import events
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import (
    CheckoutConfirmNotAllowedError,
    CheckoutRequiredError,
    InvoiceNotFoundError,
)
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.identity.models import User
from synapse_saas.subscriptions.models import Plan, Subscription
from synapse_saas.subscriptions.proration import arrears_adjustment_cents, prorate
from synapse_saas.subscriptions.service import SubscriptionService
from synapse_saas.tenancy.models import Organization

logger = get_logger(__name__)


class BillingService:
    def __init__(self, session: AsyncSession, provider: BillingProvider | None = None) -> None:
        self.session = session
        self.provider = provider or build_provider()

    # ── Customers ───────────────────────────────────────────────────────────────

    async def ensure_customer(
        self, organization: Organization, *, contact_user: User | None = None
    ) -> BillingCustomer:
        existing = (
            await self.session.execute(
                select(BillingCustomer).where(BillingCustomer.organization_id == organization.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        contact = contact_user or (
            (await self.session.get(User, organization.owner_user_id)) if organization.owner_user_id else None
        )
        ref = await self.provider.create_customer(
            CreateCustomerRequest(
                email=str(contact.email) if contact else f"{organization.slug}@example.com",
                name=contact.display_name if contact else organization.name,
                organization_id=organization.id,
                currency=get_settings().billing_currency,
            )
        )
        customer = BillingCustomer(
            organization_id=organization.id,
            provider=self.provider.name,
            provider_customer_id=ref.provider_customer_id,
            email=ref.email,
            name=ref.name,
            currency=get_settings().billing_currency,
        )
        self.session.add(customer)
        await self.session.flush()
        return customer

    # ── Checkout ────────────────────────────────────────────────────────────────

    async def start_checkout(
        self,
        organization: Organization,
        plan: Plan,
        *,
        success_url: str | None = None,
        cancel_url: str | None = None,
        contact_user: User | None = None,
    ) -> tuple[BillingCustomer, CheckoutResult]:
        """Create a checkout with the provider and return the result (URL or manual)."""
        customer = await self.ensure_customer(organization, contact_user=contact_user)
        result = await self.provider.create_checkout(
            CreateCheckoutRequest(
                plan_key=plan.key,
                plan_name=plan.name,
                price_cents=plan.price_cents or 0,
                currency=plan.currency,
                interval=plan.interval or "month",
                provider_customer_id=customer.provider_customer_id,
                success_url=success_url,
                cancel_url=cancel_url,
                organization_id=organization.id,
            )
        )
        return customer, result

    async def complete_checkout(
        self,
        organization: Organization,
        plan: Plan,
        *,
        provider_subscription_id: str | None = None,
        contact_user: User | None = None,
        source: str = "webhook",
    ) -> Subscription:
        """Activate the subscription after checkout.

        `source="webhook"` is the provider telling us payment happened.
        `source="client_confirm"` is the tenant telling us — only trustworthy
        when the provider has no payment truth of its own (CLIENT_CONFIRM).
        """
        if source == "client_confirm" and BillingCapability.CLIENT_CONFIRM not in self.provider.supports:
            raise CheckoutConfirmNotAllowedError(
                f"{self.provider.name} verifies payment via its own callback; activation "
                "happens when the provider webhook arrives, not on client confirmation",
                extras={"provider": self.provider.name},
            )
        customer = await self.ensure_customer(organization, contact_user=contact_user)
        subscriptions = SubscriptionService(self.session)
        subscription = await subscriptions.change_plan(
            organization.id,
            plan_key=plan.key,
            provider=self.provider.name,
            provider_subscription_id=provider_subscription_id,
        )
        await self._record_invoice(customer, plan)
        return subscription

    async def billing_portal_url(self, organization: Organization, *, return_url: str) -> str | None:
        if BillingCapability.BILLING_PORTAL not in self.provider.supports:
            return None
        customer = await self.ensure_customer(organization)
        if customer.provider_customer_id is None:
            return None
        return await self.provider.billing_portal_url(customer.provider_customer_id, return_url=return_url)

    # ── Invoices ────────────────────────────────────────────────────────────────

    async def invoices_for_org(self, organization_id: UUID) -> list[Invoice]:
        result = await self.session.execute(
            select(Invoice)
            .where(Invoice.organization_id == organization_id)
            .order_by(Invoice.created_at.desc())
            .limit(50)
        )
        return list(result.scalars().all())

    async def get_invoice(self, invoice_id: UUID, organization_id: UUID) -> Invoice:
        invoice = await self.session.get(Invoice, invoice_id)
        if invoice is None or invoice.organization_id != organization_id:
            raise InvoiceNotFoundError("Invoice not found")  # 404 cross-tenant
        return invoice

    async def _record_invoice(self, customer: BillingCustomer, plan: Plan) -> Invoice | None:
        if not plan.price_cents:
            return None
        invoice = Invoice(
            organization_id=customer.organization_id,
            billing_customer_id=customer.id,
            provider=self.provider.name,
            currency=plan.currency,
            subtotal_cents=plan.price_cents,
            tax_cents=0,
            total_cents=plan.price_cents,
            status="open",
        )
        self.session.add(invoice)
        await self.session.flush()
        append_outbox(
            self.session,
            event_type=events.INVOICE_CREATED,
            aggregate_type="invoice",
            aggregate_id=invoice.id,
            organization_id=customer.organization_id,
            payload={"total_cents": plan.price_cents, "currency": plan.currency, "plan_key": plan.key},
        )
        return invoice

    async def change_plan(self, organization_id: UUID, plan_key: str) -> Subscription:
        """Change the org's plan — through the provider when the provider bills.

        Rules:
        - provider bills recurring (Stripe/…): the subscription must have been
          purchased through it (`provider_subscription_id`), else 409
          `checkout_required`; the provider owns proration and invoicing.
        - otherwise (manual/Xendit/PayMongo): apply locally. paid→paid keeps
          the period and queues the prorated correction for that period's
          invoice (billed in arrears); free→paid starts a fresh cycle today.
        """
        subscriptions = SubscriptionService(self.session)
        plan = await subscriptions.plan_by_key(plan_key)
        current = await subscriptions.current_for_org(organization_id)

        if BillingCapability.RECURRING_HOSTED in self.provider.supports:
            if current is None or not current.provider_subscription_id:
                raise CheckoutRequiredError(
                    f"Plan changes on {self.provider.name} require a subscription purchased through it",
                    extras={"plan_key": plan_key, "checkout_url": "/v1/billing/checkout"},
                )
            ref = await self.provider.change_plan(
                current.provider_subscription_id,
                ChangePlanRequest(
                    plan_key=plan.key,
                    price_cents=plan.price_cents or 0,
                    currency=plan.currency,
                    interval=plan.interval or "month",
                ),
            )
            return await subscriptions.change_plan(
                organization_id,
                plan_key=plan.key,
                provider=self.provider.name,
                provider_subscription_id=ref.provider_subscription_id,
                keep_period=True,
            )

        previous = _period_snapshot(current)
        # A paid→paid switch keeps the billing period and prorates; a free→paid
        # upgrade starts a fresh cycle today (nothing to prorate on ₱0).
        keep_period = previous is not None and previous["price_cents"] > 0
        subscription = await subscriptions.change_plan(
            organization_id, plan_key=plan.key, provider=self.provider.name, keep_period=keep_period
        )
        adjustment = _proration_adjustment(previous, subscription, plan) if keep_period else None
        if adjustment is not None:
            subscription.pending_adjustments = [*subscription.pending_adjustments, adjustment]
            await self.session.flush()
            logger.info(
                "plan_change_prorated",
                org=str(organization_id),
                net_cents=adjustment["amount_cents"],
                from_plan=adjustment["from_plan"],
                to_plan=adjustment["to_plan"],
            )
        return subscription


def _period_snapshot(subscription: Subscription | None) -> dict[str, Any] | None:
    """What the org was paying, and for which period, before the change."""
    if subscription is None or subscription.status != "active":
        return None
    return {
        "plan_key": str(subscription.plan_snapshot.get("key", "")),
        "price_cents": int(subscription.plan_snapshot.get("price_cents") or 0),
        "period_start": subscription.current_period_start,
        "period_end": subscription.current_period_end,
    }


def _proration_adjustment(
    previous: dict[str, Any] | None, subscription: Subscription, plan: Plan
) -> dict[str, Any] | None:
    """Prorate the switch if the period was kept; None when nothing is owed either way."""
    if previous is None or subscription.current_period_end != previous["period_end"]:
        return None  # period reset (trial/lapsed) ⇒ the new period bills in full
    now = datetime.now(UTC)
    new_price = plan.price_cents or 0
    amount = arrears_adjustment_cents(
        previous["price_cents"], new_price, previous["period_start"], previous["period_end"], now
    )
    if amount == 0:
        return None
    elapsed = prorate(
        previous["price_cents"], new_price, previous["period_start"], previous["period_end"], now
    ).elapsed_fraction
    what = "credit" if amount < 0 else "charge"
    return {
        "kind": "proration",
        "amount_cents": amount,
        "description": (
            f"Plan change {previous['plan_key']} → {plan.key}: {what} for {elapsed:.1%} "
            f"of the period at the previous price"
        ),
        "from_plan": previous["plan_key"],
        "to_plan": plan.key,
        "from_price_cents": previous["price_cents"],
        "to_price_cents": new_price,
        "created_at": now.isoformat(),
    }
