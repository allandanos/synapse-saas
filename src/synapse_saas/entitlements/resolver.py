"""Entitlement resolution — the heart of pricing-as-config.

Pure function: DB rows in, effective feature/limit set out. No I/O, fully
unit-testable, identical semantics everywhere it runs.

Resolution rules:
1. Plan features apply iff subscription status ∈ {trialing, active, past_due}
   (past_due = grace, caller-configurable). No occupying subscription ⇒ fall
   back to the configured default plan's features.
2. Grants (entitlements table rows) apply when un-revoked and inside their
   time window. Trials, add-ons, promos, beta access, enterprise overrides —
   all the same mechanism.
3. Conflicts resolve by source priority:
   plan=0 < addon=10 < beta=20 < promo=30 < grandfather=40 < override=50 < enterprise=60
   A winning grant with enabled=False REMOVES the feature (kill switch).
4. Limits merge plan_limits overridden per-metric by grants of the synthetic
   feature key `limit:<metric>` (an add-on "extra 10k API calls" is a grant).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from synapse_saas.entitlements.models import SOURCE_PRIORITY

LIMIT_FEATURE_PREFIX = "limit:"
PLAN_SOURCE = "plan"


@dataclass(frozen=True, slots=True)
class EntitlementGrant:
    """Projection of an entitlements-table row — no ORM dependency.

    `limit_value` is only meaningful for synthetic `limit:<metric>` grants.
    """

    feature_key: str
    source: str
    enabled: bool
    starts_at: datetime
    ends_at: datetime | None
    revoked_at: datetime | None = None
    limit_value: int | None = None


@dataclass(frozen=True, slots=True)
class Limit:
    value: int | None  # None ⇒ unlimited
    soft_limit_ratio: float | None

    @property
    def is_unlimited(self) -> bool:
        return self.value is None


@dataclass(frozen=True, slots=True)
class EntitlementInputs:
    organization_id: UUID
    now: datetime
    plan_key: str | None = None
    subscription_status: str | None = None
    plan_features: frozenset[str] = frozenset()
    plan_limits: Mapping[str, Limit] = field(default_factory=dict)
    grants: tuple[EntitlementGrant, ...] = ()
    # Fallback when there is no occupying subscription (default/free plan)
    grace_on_past_due: bool = True


@dataclass(frozen=True, slots=True)
class EffectiveEntitlements:
    organization_id: UUID
    plan_key: str | None
    subscription_status: str | None
    features: frozenset[str]
    limits: Mapping[str, Limit]

    def has(self, feature: str) -> bool:
        return feature in self.features

    def limit(self, metric: str) -> Limit | None:
        return self.limits.get(metric)

    def limit_value(self, metric: str) -> int | None:
        lim = self.limits.get(metric)
        return lim.value if lim else None

    def within_limit(self, metric: str, *, used: int) -> bool:
        lim = self.limits.get(metric)
        if lim is None or lim.value is None:
            return True
        return used < lim.value


def resolve_effective(inputs: EntitlementInputs) -> EffectiveEntitlements:
    # ── 1. plan features in effect? ────────────────────────────────────────────
    status = inputs.subscription_status
    occupying = {"trialing", "active"} | ({"past_due"} if inputs.grace_on_past_due else set())
    plan_active = status in occupying if status is not None else False

    # ── 2. active grants ────────────────────────────────────────────────────────
    active_grants = tuple(g for g in inputs.grants if _grant_is_active(g, inputs.now))

    # ── 3. features: plan set, then grant overlay by priority ──────────────────
    # decision[feature] = (priority, enabled)
    decisions: dict[str, tuple[int, bool]] = {}
    if plan_active:
        for feature in inputs.plan_features:
            decisions[feature] = (SOURCE_PRIORITY[PLAN_SOURCE], True)

    for grant in active_grants:
        if grant.feature_key.startswith(LIMIT_FEATURE_PREFIX):
            continue  # handled in limit pass
        priority = SOURCE_PRIORITY.get(grant.source, 0)
        current = decisions.get(grant.feature_key)
        if current is None or priority > current[0]:
            decisions[grant.feature_key] = (priority, grant.enabled)

    features = frozenset(f for f, (_, enabled) in decisions.items() if enabled)

    # ── 4. limits: plan limits, then `limit:<metric>` grants override ──────────
    limits: dict[str, Limit] = dict(inputs.plan_limits) if plan_active else {}
    for grant in active_grants:
        if not grant.feature_key.startswith(LIMIT_FEATURE_PREFIX):
            continue
        if not grant.enabled:
            continue
        metric = grant.feature_key[len(LIMIT_FEATURE_PREFIX) :]
        base = limits.get(metric, Limit(value=None, soft_limit_ratio=None))
        limits[metric] = Limit(
            value=grant.limit_value if grant.limit_value is not None else base.value,
            soft_limit_ratio=base.soft_limit_ratio,
        )

    return EffectiveEntitlements(
        organization_id=inputs.organization_id,
        plan_key=inputs.plan_key,
        subscription_status=inputs.subscription_status,
        features=features,
        limits=limits,
    )


def _grant_is_active(grant: EntitlementGrant, now: datetime) -> bool:
    if grant.revoked_at is not None:
        return False
    if grant.starts_at > now:
        return False
    return grant.ends_at is None or now < grant.ends_at
