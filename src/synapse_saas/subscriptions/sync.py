"""Catalog → DB sync.

Idempotent upsert keyed on natural keys. Never deletes (removals become
`archived_at`), never touches `provider_refs`, never rewrites existing
subscriptions' `plan_snapshot` — YAML price changes must not rewrite history.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.core.logging import get_logger
from synapse_saas.subscriptions.catalog import PlanCatalog
from synapse_saas.subscriptions.models import Feature, Metric, Plan, PlanFeature, PlanLimit

logger = get_logger(__name__)


class SyncResult:
    def __init__(self) -> None:
        self.features_added = 0
        self.metrics_added = 0
        self.plans_added = 0
        self.plans_updated = 0
        self.plans_archived = 0

    def summary(self) -> dict[str, int]:
        return {
            "features_added": self.features_added,
            "metrics_added": self.metrics_added,
            "plans_added": self.plans_added,
            "plans_updated": self.plans_updated,
            "plans_archived": self.plans_archived,
        }


async def sync_plans(session: AsyncSession, catalog: PlanCatalog) -> SyncResult:
    result = SyncResult()
    now = datetime.now(UTC)

    # ── Features registry ───────────────────────────────────────────────────────
    existing_features = {f.key: f for f in (await session.execute(select(Feature))).scalars()}
    for feature_def in catalog.features:
        if feature_def.key in existing_features:
            continue
        session.add(Feature(key=feature_def.key, name=feature_def.name, category=feature_def.category))
        result.features_added += 1
    await session.flush()

    # ── Metrics registry ────────────────────────────────────────────────────────
    existing_metrics = {m.key: m for m in (await session.execute(select(Metric))).scalars()}
    for metric_def in catalog.metrics:
        if metric_def.key in existing_metrics:
            continue
        session.add(
            Metric(key=metric_def.key, name=metric_def.name, kind=metric_def.kind, unit=metric_def.unit)
        )
        result.metrics_added += 1
    await session.flush()

    # ── Plans ───────────────────────────────────────────────────────────────────
    existing_plans = {p.key: p for p in (await session.execute(select(Plan))).scalars()}

    for order, plan_def in enumerate(catalog.plans):
        defaults = catalog.defaults
        plan = existing_plans.get(plan_def.key)

        values = {
            "name": plan_def.name,
            "description": plan_def.description,
            "price_cents": plan_def.price_cents,
            "currency": plan_def.currency or defaults.currency,
            "interval": plan_def.interval or defaults.interval,
            "is_public": plan_def.is_public,
            "is_custom": plan_def.is_custom or plan_def.price == "custom",
            "trial_days": plan_def.trial_days if plan_def.trial_days is not None else defaults.trial_days,
            "sort_order": plan_def.sort_order or order,
            "archived_at": None,  # re-listing a plan revives it
        }

        if plan is None:
            plan = Plan(key=plan_def.key, **values)  # type: ignore[arg-type]
            session.add(plan)
            result.plans_added += 1
            await session.flush()
        else:
            changed = False
            for attr, value in values.items():
                if getattr(plan, attr) != value:
                    setattr(plan, attr, value)
                    changed = True
            if changed:
                result.plans_updated += 1
        await session.flush()

        await _sync_plan_features(session, plan.id, plan_def.features)
        await _sync_plan_limits(session, plan.id, plan_def.limits, catalog)

    # ── Archive plans removed from the catalog ─────────────────────────────────
    catalog_keys = {p.key for p in catalog.plans}
    for key, plan in existing_plans.items():
        if key not in catalog_keys and plan.archived_at is None:
            plan.archived_at = now
            result.plans_archived += 1

    logger.info("plans_synced", **result.summary())
    return result


async def _sync_plan_features(session: AsyncSession, plan_id, feature_keys: list[str]) -> None:
    existing = {
        pf.feature_key: pf
        for pf in (await session.execute(select(PlanFeature).where(PlanFeature.plan_id == plan_id))).scalars()
    }
    for key in feature_keys:
        if key not in existing:
            session.add(PlanFeature(plan_id=plan_id, feature_key=key, enabled=True))
    for key, pf in existing.items():
        if key not in feature_keys:
            await session.delete(pf)
    await session.flush()


async def _sync_plan_limits(session: AsyncSession, plan_id, limits: dict, catalog: PlanCatalog) -> None:
    existing = {
        pl.metric: pl
        for pl in (await session.execute(select(PlanLimit).where(PlanLimit.plan_id == plan_id))).scalars()
    }
    metric_defs = {m.key: m for m in catalog.metrics}

    for metric, value in limits.items():
        soft = metric_defs[metric].soft_limit_ratio if metric in metric_defs else None
        if metric in existing:
            pl = existing[metric]
            pl.limit_value = value
            pl.soft_limit_ratio = soft
        else:
            session.add(
                PlanLimit(
                    plan_id=plan_id,
                    metric=metric,
                    limit_value=value,
                    soft_limit_ratio=soft,
                )
            )
    for metric, pl in existing.items():
        if metric not in limits:
            await session.delete(pl)
    await session.flush()
