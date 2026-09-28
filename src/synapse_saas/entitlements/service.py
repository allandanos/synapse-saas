"""Entitlements service: assembles resolver inputs from the DB, caches, and manages grants."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.cache import VersionedCache, defer_bump
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import EntitlementNotFoundError, FeatureNotEntitledError, PlanNotFoundError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.entitlements.models import Entitlement
from synapse_saas.entitlements.resolver import (
    EffectiveEntitlements,
    EntitlementGrant,
    EntitlementInputs,
    Limit,
    Overage,
    resolve_effective,
)

if TYPE_CHECKING:
    from synapse_saas.subscriptions.models import Plan

logger = get_logger(__name__)

_cache = VersionedCache("entl", ttl=60)


class EntitlementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Resolution ──────────────────────────────────────────────────────────────

    async def effective_for_org(self, organization_id: UUID) -> EffectiveEntitlements:
        cache_key = str(organization_id)
        cached, version = await _cache.get_versioned(cache_key)
        if cached is not None:
            try:
                return _deserialize(cached)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # corrupt cache → recompute

        effective = await self._compute(organization_id)
        # Store under the version seen at read: a bump in between leaves the
        # new version empty instead of filling it with this (now stale) body.
        await _cache.set(cache_key, _serialize(effective), version=version)
        return effective

    async def _invalidate(self, organization_id: UUID) -> None:
        """Now (so this request recomputes) AND after commit (so no other request
        caches the pre-commit rows under the new version for a whole TTL)."""
        await _cache.bump(str(organization_id))
        defer_bump(self.session, _cache, str(organization_id))

    async def require_feature(self, organization_id: UUID, feature: str) -> EffectiveEntitlements:
        effective = await self.effective_for_org(organization_id)
        if not effective.has(feature):
            available_in = await self.plans_with_feature(feature)
            plan_key = effective.plan_key
            _inc_gated(feature)
            raise FeatureNotEntitledError(
                f"Feature {feature!r} is not available on the current plan",
                extras={
                    "feature": feature,
                    "current_plan": plan_key,
                    "available_in": available_in,
                    "upgrade_url": "/dashboard/billing",
                },
            )
        return effective

    async def plans_with_feature(self, feature: str) -> list[str]:
        from synapse_saas.subscriptions.models import Plan, PlanFeature

        rows = (
            (
                await self.session.execute(
                    select(Plan.key)
                    .join(PlanFeature, PlanFeature.plan_id == Plan.id)
                    .where(PlanFeature.feature_key == feature, PlanFeature.enabled.is_(True))
                    .order_by(Plan.sort_order)
                )
            )
            .scalars()
            .all()
        )
        return sorted(set(rows))

    # ── Grant management ────────────────────────────────────────────────────────

    async def grant(
        self,
        organization_id: UUID,
        *,
        feature_key: str,
        source: str,
        duration_days: int | None = None,
        enabled: bool = True,
        note: str | None = None,
        limit_value: int | None = None,
        created_by_user_id: UUID | None = None,
    ) -> Entitlement:
        now = datetime.now(UTC)
        ends_at = (now + timedelta(days=duration_days)) if duration_days else None
        entitlement = Entitlement(
            organization_id=organization_id,
            feature_key=feature_key,
            source=source,
            enabled=enabled,
            starts_at=now,
            ends_at=ends_at,
            note=note,
            limit_value=limit_value,
            created_by_user_id=created_by_user_id,
        )
        self.session.add(entitlement)
        await self.session.flush()

        append_outbox(
            self.session,
            event_type=events.ENTITLEMENT_GRANTED,
            aggregate_type="entitlement",
            aggregate_id=entitlement.id,
            organization_id=organization_id,
            payload={
                "feature_key": feature_key,
                "source": source,
                "ends_at": ends_at.isoformat() if ends_at else None,
                "limit_value": limit_value,
            },
        )
        await self._invalidate(organization_id)
        return entitlement

    async def get(self, entitlement_id: UUID) -> Entitlement:
        entitlement = await self.session.get(Entitlement, entitlement_id)
        if entitlement is None:
            raise EntitlementNotFoundError("Grant not found", extras={"entitlement_id": str(entitlement_id)})
        return entitlement

    async def revoke(self, entitlement_id: UUID) -> Entitlement:
        entitlement = await self.session.get(Entitlement, entitlement_id)
        if entitlement is None:
            raise EntitlementNotFoundError("Entitlement not found")
        entitlement.revoked_at = datetime.now(UTC)
        await self.session.flush()

        append_outbox(
            self.session,
            event_type=events.ENTITLEMENT_REVOKED,
            aggregate_type="entitlement",
            aggregate_id=entitlement.id,
            organization_id=entitlement.organization_id,
            payload={"feature_key": entitlement.feature_key},
        )
        await self._invalidate(entitlement.organization_id)
        return entitlement

    # ── Internals ───────────────────────────────────────────────────────────────

    async def _compute(self, organization_id: UUID) -> EffectiveEntitlements:
        from synapse_saas.subscriptions.service import SubscriptionService

        settings = get_settings()
        subscriptions = SubscriptionService(self.session)
        subscription = await subscriptions.current_for_org(organization_id)

        plan: Plan | None = None
        if subscription is not None:
            plan = subscription.plan
        else:
            # No occupying subscription ⇒ default plan (free) so a fresh org
            # resolves sensible features/limits
            try:
                plan = await subscriptions.plan_by_key(settings.default_plan_key)
            except PlanNotFoundError:
                plan = None  # no catalog seeded yet ⇒ no plan features/limits
            # Any other failure (DB down, aborted transaction) propagates: an
            # org must never silently resolve to "zero features".

        rows = (
            (
                await self.session.execute(
                    select(Entitlement).where(
                        Entitlement.organization_id == organization_id,
                        Entitlement.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        grants = tuple(
            EntitlementGrant(
                feature_key=row.feature_key,
                source=row.source,
                enabled=row.enabled,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                revoked_at=row.revoked_at,
                limit_value=row.limit_value,
            )
            for row in rows
        )

        plan_features = frozenset(pf.feature_key for pf in (plan.features if plan else []))
        plan_limits = {
            pl.metric: Limit(
                value=pl.limit_value,
                soft_limit_ratio=float(pl.soft_limit_ratio) if pl.soft_limit_ratio else None,
                overage=(
                    Overage(unit=pl.overage_unit, price_cents=pl.overage_price_cents)
                    if pl.overage_unit is not None and pl.overage_price_cents is not None
                    else None
                ),
            )
            for pl in (plan.limits if plan else [])
        }

        from synapse_saas.subscriptions.models import Metric

        metric_rows = (
            await self.session.execute(select(Metric).where(Metric.overage_price_cents.is_not(None)))
        ).scalars()
        metric_overage = {
            m.key: Overage(unit=m.overage_unit or 1, price_cents=int(m.overage_price_cents or 0))
            for m in metric_rows
        }

        inputs = EntitlementInputs(
            organization_id=organization_id,
            now=datetime.now(UTC),
            plan_key=plan.key if plan else None,
            subscription_status=subscription.status if subscription else None,
            plan_features=plan_features,
            plan_limits=plan_limits,
            grants=grants,
            metric_overage=metric_overage,
            grace_on_past_due=settings.grace_on_past_due,
        )
        return resolve_effective(inputs)


def _serialize(effective: EffectiveEntitlements) -> str:
    return json.dumps(
        {
            "organization_id": str(effective.organization_id),
            "plan_key": effective.plan_key,
            "subscription_status": effective.subscription_status,
            "features": sorted(effective.features),
            "limits": {
                metric: {
                    "value": lim.value,
                    "soft_limit_ratio": lim.soft_limit_ratio,
                    "overage": (
                        {"unit": lim.overage.unit, "price_cents": lim.overage.price_cents}
                        if lim.overage is not None
                        else None
                    ),
                }
                for metric, lim in effective.limits.items()
            },
        }
    )


def _deserialize(raw: str) -> EffectiveEntitlements:
    data = json.loads(raw)
    return EffectiveEntitlements(
        organization_id=UUID(data["organization_id"]),
        plan_key=data["plan_key"],
        subscription_status=data["subscription_status"],
        features=frozenset(data["features"]),
        limits={
            metric: Limit(
                value=lim["value"],
                soft_limit_ratio=lim.get("soft_limit_ratio"),
                overage=(
                    Overage(unit=int(lim["overage"]["unit"]), price_cents=int(lim["overage"]["price_cents"]))
                    if lim.get("overage")
                    else None
                ),
            )
            for metric, lim in data["limits"].items()
        },
    )


def _inc_gated(feature: str) -> None:
    try:
        from synapse_saas.core import metrics

        metrics.FEATURE_GATED.labels(feature=feature).inc()
    except Exception as exc:  # metrics must never fail the request
        logger.debug("metrics_inc_failed", metric="feature_gated", error=str(exc))


async def invalidate_entitlements(organization_id: str) -> None:
    """Out-of-session invalidation (worker jobs, after their own commit)."""
    await _cache.bump(organization_id)
