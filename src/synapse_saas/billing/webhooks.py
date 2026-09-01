"""Billing webhook ingest.

Pipeline per event:
1. verify signature (provider-specific, raw bytes)
2. insert into provider_webhook_events ON CONFLICT DO NOTHING — duplicate ⇒ 200 no-op
3. translate to NormalizedBillingEvent list
4. apply each idempotently (upserts keyed on provider ids + state machine)

Provider retries and out-of-order delivery are safe by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.audit.models import ProviderWebhookEvent
from synapse_saas.billing.models import BillingCustomer, Invoice
from synapse_saas.billing.protocol import (
    BillingProvider,
    NormalizedBillingEvent,
    WebhookRequest,
)
from synapse_saas.billing.registry import build_provider_by_name
from synapse_saas.core import events as event_constants
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.subscriptions.models import Subscription
from synapse_saas.subscriptions.service import SubscriptionService
from synapse_saas.tenancy.models import Organization

logger = get_logger(__name__)


class BillingWebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle(
        self, provider_name: str, raw: WebhookRequest, provider: BillingProvider | None = None
    ) -> dict[str, Any]:
        provider = provider or build_provider_by_name(provider_name)
        verified = await provider.verify_webhook(raw)

        # Idempotency ledger: a no-op insert means the event was already processed
        stmt = (
            pg_insert(ProviderWebhookEvent)
            .values(
                provider=provider_name,
                provider_event_id=verified.provider_event_id,
                event_type=verified.event_type,
            )
            .on_conflict_do_nothing(index_elements=["provider", "provider_event_id"])
            .returning(ProviderWebhookEvent.id)
        )
        inserted = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted is None:
            logger.info(
                "webhook_duplicate_ignored",
                provider=provider_name,
                provider_event=verified.provider_event_id,
            )
            return {"status": "duplicate", "events_applied": 0}

        normalized = provider.translate_webhook(verified)
        applied = 0
        for event in normalized:
            try:
                await self._apply(provider_name, event)
                applied += 1
            except Exception as exc:
                logger.warning(
                    "webhook_event_apply_failed",
                    provider=provider_name,
                    event_type=event.event_type,
                    error=str(exc),
                )

        now = datetime.now(UTC)
        from sqlalchemy import update

        await self.session.execute(
            update(ProviderWebhookEvent).where(ProviderWebhookEvent.id == inserted).values(processed_at=now)
        )
        return {"status": "processed", "events_applied": applied}

    # ── Application ─────────────────────────────────────────────────────────────

    async def _apply(self, provider_name: str, event: NormalizedBillingEvent) -> None:
        org_id = await self._org_for_customer(event.provider_customer_id)
        if org_id is None and event.provider_subscription_id:
            org_id = await self._org_for_subscription(event.provider_subscription_id)
        if org_id is None:
            logger.debug("webhook_event_no_org", event_type=event.event_type)
            return

        match event.event_type:
            case (
                NormalizedBillingEvent.SUBSCRIPTION_ACTIVATED
                | NormalizedBillingEvent.SUBSCRIPTION_CREATED
                | NormalizedBillingEvent.SUBSCRIPTION_TRIAL_ENDED
            ):
                await self._apply_status(org_id, event, "active")
            case NormalizedBillingEvent.SUBSCRIPTION_UPDATED:
                await self._apply_status(org_id, event, event.status or "active")
            case NormalizedBillingEvent.SUBSCRIPTION_CANCELED:
                await self._apply_status(org_id, event, "canceled")
            case NormalizedBillingEvent.SUBSCRIPTION_PAST_DUE:
                await self._apply_status(org_id, event, "past_due")
            case NormalizedBillingEvent.INVOICE_PAID:
                await self._upsert_invoice(provider_name, org_id, event, "paid")
            case NormalizedBillingEvent.INVOICE_CREATED:
                await self._upsert_invoice(provider_name, org_id, event, "open")
            case NormalizedBillingEvent.INVOICE_FAILED:
                await self._upsert_invoice(provider_name, org_id, event, "uncollectible")
            case NormalizedBillingEvent.CHECKOUT_COMPLETED:
                await self._apply_checkout_completed(org_id, event)
            case _:
                logger.debug("webhook_event_ignored", event_type=event.event_type)

    async def _apply_status(self, org_id: UUID, event: NormalizedBillingEvent, target_status: str) -> None:
        subscriptions = SubscriptionService(self.session)
        subscription = await subscriptions.current_for_org(org_id)
        if subscription is None:
            logger.debug("webhook_status_no_subscription", org_id=str(org_id))
            return
        await subscriptions.apply_provider_transition(
            subscription,
            target_status=target_status,
            current_period_end=event.current_period_end,
        )
        append_outbox(
            self.session,
            event_type=event_constants.SUBSCRIPTION_UPDATED,
            aggregate_type="subscription",
            aggregate_id=subscription.id,
            organization_id=org_id,
            payload={"status": target_status, "provider_event": event.event_type},
        )

    async def _apply_checkout_completed(self, org_id: UUID, event: NormalizedBillingEvent) -> None:
        from synapse_saas.billing.service import BillingService

        if not event.plan_key:
            logger.debug("checkout_completed_no_plan", org_id=str(org_id))
            return
        billing = BillingService(self.session)
        subscriptions = SubscriptionService(self.session)
        plan = await subscriptions.plan_by_key(event.plan_key)
        org = (await self.session.execute(select(Organization).where(Organization.id == org_id))).scalar_one()
        await billing.complete_checkout(org, plan, provider_subscription_id=event.provider_subscription_id)

    async def _upsert_invoice(
        self, provider_name: str, org_id: UUID, event: NormalizedBillingEvent, status: str
    ) -> None:
        if not event.provider_invoice_id:
            return
        customer = (
            await self.session.execute(
                select(BillingCustomer).where(BillingCustomer.organization_id == org_id)
            )
        ).scalar_one_or_none()

        invoice = (
            await self.session.execute(
                select(Invoice).where(
                    Invoice.provider == provider_name,
                    Invoice.provider_invoice_id == event.provider_invoice_id,
                )
            )
        ).scalar_one_or_none()

        if invoice is None:
            invoice = Invoice(organization_id=org_id)
            self.session.add(invoice)
        invoice.provider = provider_name
        invoice.provider_invoice_id = event.provider_invoice_id
        invoice.billing_customer_id = customer.id if customer else None
        invoice.currency = event.currency or "PHP"
        invoice.total_cents = event.amount_cents or 0
        invoice.status = status
        invoice.hosted_url = event.hosted_url
        if status == "paid":
            invoice.paid_at = event.occurred_at
        await self.session.flush()

        if status == "paid":
            append_outbox(
                self.session,
                event_type=event_constants.INVOICE_PAID,
                aggregate_type="invoice",
                aggregate_id=invoice.id,
                organization_id=org_id,
                payload={"total_cents": invoice.total_cents, "currency": invoice.currency},
            )

    # ── Org lookup ──────────────────────────────────────────────────────────────

    async def _org_for_customer(self, provider_customer_id: str | None) -> UUID | None:
        if not provider_customer_id:
            return None
        return (
            await self.session.execute(
                select(BillingCustomer.organization_id).where(
                    BillingCustomer.provider_customer_id == provider_customer_id
                )
            )
        ).scalar_one_or_none()

    async def _org_for_subscription(self, provider_subscription_id: str | None) -> UUID | None:
        if not provider_subscription_id:
            return None
        return (
            await self.session.execute(
                select(Subscription.organization_id).where(
                    Subscription.provider_subscription_id == provider_subscription_id
                )
            )
        ).scalar_one_or_none()
