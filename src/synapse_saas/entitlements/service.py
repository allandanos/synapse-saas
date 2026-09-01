"""Entitlements service: assembles resolver inputs from the DB, caches, and manages grants."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core import events
from synapse_saas.core.cache import VersionedCache
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import EntitlementNotFoundError, FeatureNotEntitledError
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox
from synapse_saas.entitlements.models import Entitlement
from synapse_saas.entitlements.resolver import (
    EffectiveEntitlements,
    EntitlementGrant,
    EntitlementInputs,
    Limit,
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
        cached = await _cache.get(cache_key)
        if cached is not None:
            try:
                return _deserialize(cached)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # corrupt cache → recompute

        effective = await self._compute(organization_id)
        await _cache.set(cache_key, _serialize(effective))
        return effective

    async def require_feature(self, organization_id: UUID, feature: str) -> EffectiveEntitlements:
        effective = await self.effective_for_org(organization_id)
        if not effective.has(feature):
            available_in = await self.plans_with_feature(feature)
            plan_key = effective.plan_key
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
            note=note if note is not None or limit_value is None else f"limit={limit_value}",
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
        await _cache.bump(str(organization_id))
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
        await _cache.bump(str(entitlement.organization_id))
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
            except Exception:
                plan = None

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
                limit_value=_limit_value_from_note(row.note),
            )
            for row in rows
        )

        plan_features = frozenset(pf.feature_key for pf in (plan.features if plan else []))
        plan_limits = {
            pl.metric: Limit(
                value=pl.limit_value,
                soft_limit_ratio=float(pl.soft_limit_ratio) if pl.soft_limit_ratio else None,
            )
            for pl in (plan.limits if plan else [])
        }

        inputs = EntitlementInputs(
            organization_id=organization_id,
            now=datetime.now(UTC),
            plan_key=plan.key if plan else None,
            subscription_status=subscription.status if subscription else None,
            plan_features=plan_features,
            plan_limits=plan_limits,
            grants=grants,
            grace_on_past_due=settings.grace_on_past_due,
        )
        return resolve_effective(inputs)


def _limit_value_from_note(note: str | None) -> int | None:
    """Limit-addon grants encode their value in the note field (`limit=123`)."""
    if not note or not note.startswith("limit="):
        return None
    try:
        return int(note.removeprefix("limit="))
    except ValueError:
        return None


def _serialize(effective: EffectiveEntitlements) -> str:
    return json.dumps(
        {
            "organization_id": str(effective.organization_id),
            "plan_key": effective.plan_key,
            "subscription_status": effective.subscription_status,
            "features": sorted(effective.features),
            "limits": {
                metric: {"value": lim.value, "soft_limit_ratio": lim.soft_limit_ratio}
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
            metric: Limit(value=lim["value"], soft_limit_ratio=lim.get("soft_limit_ratio"))
            for metric, lim in data["limits"].items()
        },
    )
