"""Subscription domain service.

Owns the subscription lifecycle: create, trial, plan change, cancel/resume.
Plan changes capture a `plan_snapshot` (grandfathering) and always bump the
entitlements cache version.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.cache import VersionedCache
from synapse_saas.core.errors import (
    PlanNotFoundError,
    SubscriptionNotFoundError,
    TrialNotAllowedError,
)
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.subscriptions.models import Plan, Subscription
from synapse_saas.subscriptions.state_machine import OCCUPYING_STATUSES, assert_transition

logger = get_logger(__name__)

_entitlement_cache = VersionedCache("entl")

MONTH = timedelta(days=30)
YEAR = timedelta(days=365)


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Queries ─────────────────────────────────────────────────────────────────

    async def current_for_org(self, organization_id: UUID) -> Subscription | None:
        """The occupying subscription (trialing/active/past_due), if any.

        `plan` is eager-loaded: responses serialize plan features/limits.
        """
        from sqlalchemy.orm import selectinload

        result = await self.session.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan).selectinload(Plan.features))
            .options(selectinload(Subscription.plan).selectinload(Plan.limits))
            .where(
                Subscription.organization_id == organization_id,
                Subscription.status.in_(OCCUPYING_STATUSES),
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_404(self, subscription_id: UUID) -> Subscription:
        subscription = await self.session.get(Subscription, subscription_id)
        if subscription is None:
            raise SubscriptionNotFoundError("Subscription not found")
        return subscription

    async def plan_by_key(self, key: str, *, include_archived: bool = False) -> Plan:
        """Plan with features/limits eager-loaded (snapshots and responses need them)."""
        from sqlalchemy.orm import selectinload

        stmt = select(Plan).options(selectinload(Plan.features), selectinload(Plan.limits))
        stmt = stmt.where(Plan.key == key)
        if not include_archived:
            stmt = stmt.where(Plan.archived_at.is_(None))
        plan = (await self.session.execute(stmt)).scalar_one_or_none()
        if plan is None:
            raise PlanNotFoundError(f"Plan {key!r} not found")
        return plan

    # ── Commands ────────────────────────────────────────────────────────────────

    async def create_subscription(
        self,
        *,
        organization_id: UUID,
        plan: Plan,
        status: str = "active",
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        trial_ends_at: datetime | None = None,
        provider: str | None = None,
        provider_subscription_id: str | None = None,
        billing_customer_id: UUID | None = None,
    ) -> Subscription:
        now = datetime.now(UTC)
        interval_delta = YEAR if plan.interval == "year" else MONTH
        start = current_period_start or now
        end = current_period_end or (start + interval_delta)

        subscription = Subscription(
            organization_id=organization_id,
            plan_id=plan.id,
            status=status,
            current_period_start=start,
            current_period_end=end,
            trial_ends_at=trial_ends_at,
            provider=provider,
            provider_subscription_id=provider_subscription_id,
            billing_customer_id=billing_customer_id,
            plan_snapshot=_snapshot(plan),
        )
        self.session.add(subscription)
        await self.session.flush()

        event = events.SUBSCRIPTION_TRIAL_STARTED if status == "trialing" else events.SUBSCRIPTION_ACTIVATED
        self._emit(
            event,
            subscription,
            plan,
            extra={"organization_id": str(organization_id)},
        )
        await self._bump_cache(organization_id)
        # Responses serialize subscription.plan (features/limits); assign the
        # already-loaded plan object so no lazy load fires at serialization.
        subscription.plan = plan
        return subscription

    async def start_trial(
        self,
        organization_id: UUID,
        *,
        plan_key: str,
        trial_days: int | None = None,
    ) -> Subscription:
        """Replace the occupying subscription with a trialing one on `plan_key`."""
        plan = await self.plan_by_key(plan_key)
        if plan.trial_days == 0 and trial_days is None:
            raise TrialNotAllowedError(f"Plan {plan_key!r} has no trial period")

        existing = await self.current_for_org(organization_id)
        if existing is not None and existing.status == "trialing":
            raise TrialNotAllowedError("A trial is already in progress for this organization")

        days = trial_days if trial_days is not None else plan.trial_days
        now = datetime.now(UTC)
        trial_end = now + timedelta(days=days)

        if existing is not None:
            # End the current subscription, then trial on top
            assert_transition(existing.status, "canceled")
            existing.status = "canceled"
            existing.canceled_at = now

        subscription = await self.create_subscription(
            organization_id=organization_id,
            plan=plan,
            status="trialing",
            current_period_start=now,
            current_period_end=trial_end,
            trial_ends_at=trial_end,
        )
        self._audit(
            events.SUBSCRIPTION_TRIAL_STARTED,
            organization_id,
            target_type="subscription",
            target_id=subscription.id,
            diff={"plan": plan_key, "trial_days": days},
        )
        return subscription

    async def change_plan(
        self,
        organization_id: UUID,
        *,
        plan_key: str,
        provider: str | None = None,
        provider_subscription_id: str | None = None,
    ) -> Subscription:
        """Switch the occupying subscription to a new plan immediately (upgrade path)."""
        plan = await self.plan_by_key(plan_key)
        existing = await self.current_for_org(organization_id)
        now = datetime.now(UTC)
        interval_delta = YEAR if plan.interval == "year" else MONTH

        if existing is None:
            return await self.create_subscription(
                organization_id=organization_id,
                plan=plan,
                status="active",
                provider=provider,
                provider_subscription_id=provider_subscription_id,
            )

        from_snapshot = existing.plan_snapshot.get("key")
        existing.status = "active" if existing.status != "active" else existing.status
        existing.plan_id = plan.id
        existing.plan_snapshot = _snapshot(plan)
        existing.current_period_start = now
        existing.current_period_end = now + interval_delta
        existing.cancel_at_period_end = False
        existing.canceled_at = None
        if provider is not None:
            existing.provider = provider
        if provider_subscription_id is not None:
            existing.provider_subscription_id = provider_subscription_id
        await self.session.flush()
        existing.plan = plan  # already loaded — avoid lazy load at serialization

        self._emit(
            events.SUBSCRIPTION_PLAN_CHANGED,
            existing,
            plan,
            extra={"from_plan": str(from_snapshot), "to_plan": plan.key},
        )
        self._audit(
            events.SUBSCRIPTION_PLAN_CHANGED,
            organization_id,
            target_type="subscription",
            target_id=existing.id,
            diff={"from": from_snapshot, "to": plan.key},
        )
        await self._bump_cache(organization_id)
        return existing

    async def cancel(self, organization_id: UUID, *, at_period_end: bool = True) -> Subscription:
        subscription = await self._require_current(organization_id)
        now = datetime.now(UTC)
        assert_transition(subscription.status, "canceled")

        if at_period_end:
            subscription.cancel_at_period_end = True
        else:
            subscription.status = "canceled"
            subscription.canceled_at = now

        self._emit(events.SUBSCRIPTION_CANCELED, subscription, subscription.plan)
        self._audit(
            events.SUBSCRIPTION_CANCELED,
            organization_id,
            target_type="subscription",
            target_id=subscription.id,
            diff={"at_period_end": at_period_end},
        )
        await self._bump_cache(organization_id)
        return subscription

    async def resume(self, organization_id: UUID) -> Subscription:
        subscription = await self._require_current(organization_id)
        if subscription.cancel_at_period_end:
            subscription.cancel_at_period_end = False
            self._emit(events.SUBSCRIPTION_RESUMED, subscription, subscription.plan)
            await self._bump_cache(organization_id)
            return subscription
        raise SubscriptionNotFoundError("Subscription is not scheduled for cancellation")

    async def apply_provider_transition(
        self,
        subscription: Subscription,
        *,
        target_status: str,
        current_period_end: datetime | None = None,
    ) -> Subscription:
        """Webhook-driven status change; idempotent and transition-checked."""
        assert_transition(subscription.status, target_status)
        subscription.status = target_status
        if current_period_end is not None:
            subscription.current_period_end = current_period_end
        await self.session.flush()
        await self._bump_cache(subscription.organization_id)
        return subscription

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _require_current(self, organization_id: UUID) -> Subscription:
        subscription = await self.current_for_org(organization_id)
        if subscription is None:
            raise SubscriptionNotFoundError("No active subscription for this organization")
        return subscription

    def _emit(
        self, event_type: str, subscription: Subscription, plan: Plan, *, extra: dict | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "subscription_id": str(subscription.id),
            "organization_id": str(subscription.organization_id),
            "plan_key": plan.key,
            "status": subscription.status,
        }
        if extra:
            payload.update(extra)
        append_outbox(
            self.session,
            event_type=event_type,
            aggregate_type="subscription",
            aggregate_id=subscription.id,
            organization_id=subscription.organization_id,
            payload=payload,
        )

    def _audit(
        self,
        event_type: str,
        organization_id: UUID,
        *,
        target_type: str,
        target_id: uuid.UUID,
        diff: dict | None,
    ) -> None:
        from synapse_saas.audit.service import AuditService

        AuditService(self.session).log(
            event_type,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            diff=diff,
        )

    async def _bump_cache(self, organization_id: UUID) -> None:
        await _entitlement_cache.bump(str(organization_id))


def _snapshot(plan: Plan) -> dict[str, Any]:
    """Freeze purchase-time pricing/features so later YAML edits never rewrite history."""
    return {
        "key": plan.key,
        "name": plan.name,
        "price_cents": plan.price_cents,
        "currency": plan.currency,
        "interval": plan.interval,
        "features": [pf.feature_key for pf in plan.features if pf.enabled],
        "limits": {pl.metric: pl.limit_value for pl in plan.limits},
    }
