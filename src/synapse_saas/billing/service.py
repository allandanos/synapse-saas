"""Billing domain service.

Customer management, checkout, plan changes through the active provider.
Provider calls happen BEFORE the DB mutation so a failed provider call leaves
no local state behind.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.billing.models import BillingCustomer, Invoice
from synapse_saas.billing.protocol import (
    BillingCapability,
    BillingProvider,
    ChangePlanRequest,
    CreateCheckoutRequest,
    CreateCustomerRequest,
)
from synapse_saas.billing.registry import build_provider
from synapse_saas.core import events
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import InvoiceNotFoundError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.identity.models import User
from synapse_saas.subscriptions.models import Plan
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
    ):
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
    ):
        """Activate the subscription after checkout (webhook or manual confirm)."""
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

    async def change_plan_remote(
        self, organization: Organization, plan: Plan, *, provider_subscription_id: str
    ):
        """Push a plan change through the provider, then update locally."""
        if BillingCapability.RECURRING_HOSTED not in self.provider.supports:
            # Manual/xendit/paymongo: apply locally, the scheduler owns renewals
            return await SubscriptionService(self.session).change_plan(
                organization.id, plan_key=plan.key, provider=self.provider.name
            )
        ref = await self.provider.change_plan(
            provider_subscription_id,
            ChangePlanRequest(
                plan_key=plan.key,
                price_cents=plan.price_cents or 0,
                currency=plan.currency,
                interval=plan.interval or "month",
            ),
        )
        return await SubscriptionService(self.session).change_plan(
            organization.id,
            plan_key=plan.key,
            provider=self.provider.name,
            provider_subscription_id=ref.provider_subscription_id,
        )
