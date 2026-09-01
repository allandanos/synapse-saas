"""Entitlement resolver test matrix.

The pure function that turns (plan + subscription + grants) into the effective
feature/limit set. Every pricing behavior the framework promises is pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synapse_saas.entitlements.resolver import (
    EntitlementGrant,
    EntitlementInputs,
    Limit,
    resolve_effective,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
PLAN_FEATURES = frozenset({"basic_dashboard", "api_access", "advanced_reports"})
PLAN_LIMITS = {
    "users": Limit(value=10, soft_limit_ratio=None),
    "api_requests": Limit(value=100_000, soft_limit_ratio=0.8),
    "storage_bytes": Limit(value=None, soft_limit_ratio=None),  # unlimited
}


def make_inputs(**overrides) -> EntitlementInputs:
    defaults: dict = {
        "organization_id": uuid4(),
        "now": NOW,
        "plan_key": "pro",
        "subscription_status": "active",
        "plan_features": PLAN_FEATURES,
        "plan_limits": PLAN_LIMITS,
        "grants": (),
    }
    defaults.update(overrides)
    return EntitlementInputs(**defaults)


def grant(
    feature: str,
    source: str = "override",
    *,
    enabled: bool = True,
    starts_at: datetime = NOW - timedelta(days=1),
    ends_at: datetime | None = None,
    revoked_at: datetime | None = None,
    limit_value: int | None = None,
) -> EntitlementGrant:
    return EntitlementGrant(
        feature_key=feature,
        source=source,
        enabled=enabled,
        starts_at=starts_at,
        ends_at=ends_at,
        revoked_at=revoked_at,
        limit_value=limit_value,
    )


class TestPlanFeatures:
    def test_active_subscription_has_plan_features(self) -> None:
        result = resolve_effective(make_inputs())
        assert result.has("advanced_reports")
        assert result.features == PLAN_FEATURES

    @pytest.mark.parametrize("status", ["trialing", "past_due"])
    def test_trialing_and_past_due_keep_features(self, status: str) -> None:
        result = resolve_effective(make_inputs(subscription_status=status))
        assert result.has("advanced_reports")

    def test_past_due_grace_disabled(self) -> None:
        result = resolve_effective(make_inputs(subscription_status="past_due", grace_on_past_due=False))
        assert not result.has("advanced_reports")
        assert result.features == frozenset()

    @pytest.mark.parametrize("status", ["canceled", "unpaid", "incomplete"])
    def test_dead_statuses_lose_features(self, status: str) -> None:
        result = resolve_effective(make_inputs(subscription_status=status))
        assert result.features == frozenset()
        assert result.limits == {}

    def test_no_subscription_no_features(self) -> None:
        result = resolve_effective(make_inputs(subscription_status=None, plan_key=None))
        assert result.features == frozenset()


class TestGrants:
    def test_trial_grant_adds_feature_independent_of_plan(self) -> None:
        inputs = make_inputs(
            subscription_status="canceled",
            grants=(grant("advanced_reports", "trial", ends_at=NOW + timedelta(days=14)),),
        )
        result = resolve_effective(inputs)
        assert result.has("advanced_reports")

    def test_expired_grant_ignored(self) -> None:
        inputs = make_inputs(grants=(grant("beta_feature", "beta", ends_at=NOW - timedelta(days=1)),))
        assert not resolve_effective(inputs).has("beta_feature")

    def test_future_grant_ignored(self) -> None:
        inputs = make_inputs(grants=(grant("beta_feature", "beta", starts_at=NOW + timedelta(days=1)),))
        assert not resolve_effective(inputs).has("beta_feature")

    def test_revoked_grant_ignored(self) -> None:
        inputs = make_inputs(grants=(grant("beta_feature", "beta", revoked_at=NOW - timedelta(hours=1)),))
        assert not resolve_effective(inputs).has("beta_feature")

    def test_disabled_grant_kills_plan_feature(self) -> None:
        """The kill switch: an override can REMOVE a plan feature."""
        inputs = make_inputs(grants=(grant("advanced_reports", "override", enabled=False),))
        result = resolve_effective(inputs)
        assert not result.has("advanced_reports")
        assert result.has("basic_dashboard")

    def test_priority_enterprise_beats_override(self) -> None:
        inputs = make_inputs(
            grants=(
                grant("advanced_reports", "override", enabled=False),
                grant("advanced_reports", "enterprise", enabled=True),
            )
        )
        assert resolve_effective(inputs).has("advanced_reports")

    def test_priority_higher_source_wins_regardless_of_order(self) -> None:
        inputs = make_inputs(
            grants=(
                grant("beta_feature", "enterprise", enabled=False),
                grant("beta_feature", "promo", enabled=True),
            )
        )
        assert not resolve_effective(inputs).has("beta_feature")

    def test_grant_works_with_no_plan_at_all(self) -> None:
        inputs = make_inputs(
            subscription_status=None,
            plan_key=None,
            grants=(grant("sso", "enterprise"),),
        )
        assert resolve_effective(inputs).has("sso")


class TestLimits:
    def test_plan_limits_resolved(self) -> None:
        result = resolve_effective(make_inputs())
        assert result.limit_value("users") == 10
        assert result.limit_value("api_requests") == 100_000
        assert result.limit("api_requests").soft_limit_ratio == 0.8

    def test_unlimited(self) -> None:
        result = resolve_effective(make_inputs())
        assert result.limit("storage_bytes").is_unlimited
        assert result.within_limit("storage_bytes", used=10**12)

    def test_within_limit_boundary(self) -> None:
        result = resolve_effective(make_inputs())
        assert result.within_limit("users", used=9)
        assert not result.within_limit("users", used=10)

    def test_unknown_metric_is_unlimited(self) -> None:
        result = resolve_effective(make_inputs())
        assert result.limit("ai_tokens") is None
        assert result.within_limit("ai_tokens", used=10**9)

    def test_limit_addon_grant_raises_cap(self) -> None:
        inputs = make_inputs(grants=(grant("limit:api_requests", "addon", limit_value=500_000),))
        result = resolve_effective(inputs)
        assert result.limit_value("api_requests") == 500_000
        assert result.limit("api_requests").soft_limit_ratio == 0.8  # preserved

    def test_limit_grant_on_dead_subscription(self) -> None:
        inputs = make_inputs(
            subscription_status="canceled",
            grants=(grant("limit:api_requests", "addon", limit_value=50),),
        )
        result = resolve_effective(inputs)
        assert result.limit_value("api_requests") == 50

    def test_disabled_limit_grant_ignored(self) -> None:
        inputs = make_inputs(
            grants=(grant("limit:api_requests", "addon", enabled=False, limit_value=500_000),)
        )
        assert resolve_effective(inputs).limit_value("api_requests") == 100_000


class TestMetadata:
    def test_carries_plan_and_status(self) -> None:
        result = resolve_effective(make_inputs())
        assert result.plan_key == "pro"
        assert result.subscription_status == "active"
