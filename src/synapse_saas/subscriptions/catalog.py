"""Plan catalog: YAML → validated pydantic models.

Fails fast at startup on any inconsistency (unknown feature/metric, duplicate
keys, custom-price mismatches). The catalog is the pricing source of truth;
the DB is a projection of it (see subscriptions/sync.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from synapse_saas.core.errors import CatalogInvalidError


class CatalogDefaults(BaseModel):
    currency: str = Field("PHP", pattern=r"^[A-Z]{3}$")
    interval: str = Field("month", pattern=r"^(month|year)$")
    trial_days: int = Field(0, ge=0)
    soft_limit_ratio: float | None = Field(0.8, ge=0, le=1)


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    category: str | None = None


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    kind: Literal["counter", "gauge"]
    unit: str | None = None
    soft_limit_ratio: float | None = Field(None, ge=0, le=1)


class PlanDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    description: str | None = None
    # Exactly one of price_cents / price: custom must be set (xor)
    price_cents: int | None = Field(None, ge=0)
    price: Literal["custom"] | None = None
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    interval: str | None = Field(None, pattern=r"^(month|year)$")
    is_public: bool = True
    is_custom: bool = False
    trial_days: int | None = Field(None, ge=0)
    sort_order: int = 0
    features: list[str] = Field(default_factory=list)
    # value omitted or null ⇒ unlimited
    limits: dict[str, int | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _price_xor(self) -> Self:
        has_cents = self.price_cents is not None
        is_custom = self.price == "custom"
        if has_cents and is_custom:
            raise ValueError(f"plan {self.key!r}: set either price_cents or price: custom, not both")
        if not has_cents and not is_custom:
            raise ValueError(f"plan {self.key!r}: must set price_cents or price: custom")
        return self


class PlanCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    defaults: CatalogDefaults = CatalogDefaults()
    features: list[FeatureDefinition]
    metrics: list[MetricDefinition]
    plans: list[PlanDefinition]

    @model_validator(mode="after")
    def _cross_validate(self) -> Self:
        errors: list[str] = []

        feature_keys = [f.key for f in self.features]
        dup_features = {k for k in feature_keys if feature_keys.count(k) > 1}
        if dup_features:
            errors.append(f"duplicate feature keys: {sorted(dup_features)}")

        metric_keys = [m.key for m in self.metrics]
        dup_metrics = {k for k in metric_keys if metric_keys.count(k) > 1}
        if dup_metrics:
            errors.append(f"duplicate metric keys: {sorted(dup_metrics)}")

        plan_keys = [p.key for p in self.plans]
        dup_plans = {k for k in plan_keys if plan_keys.count(k) > 1}
        if dup_plans:
            errors.append(f"duplicate plan keys: {sorted(dup_plans)}")

        feature_set = set(feature_keys)
        metric_set = set(metric_keys)

        for plan in self.plans:
            unknown = set(plan.features) - feature_set
            if unknown:
                errors.append(f"plan {plan.key!r} references unknown features: {sorted(unknown)}")
            unknown_metrics = set(plan.limits) - metric_set
            if unknown_metrics:
                errors.append(f"plan {plan.key!r} limits unknown metrics: {sorted(unknown_metrics)}")
            if plan.is_public and plan.price_cents is None:
                errors.append(f"public plan {plan.key!r} must have a concrete price_cents")

        if errors:
            raise CatalogInvalidError(
                "Invalid plan catalog",
                extras={"errors": errors},
            )
        return self

    def feature_keys(self) -> frozenset[str]:
        return frozenset(f.key for f in self.features)

    def metric_keys(self) -> frozenset[str]:
        return frozenset(m.key for m in self.metrics)

    def plan(self, key: str) -> PlanDefinition | None:
        return next((p for p in self.plans if p.key == key), None)


def load_catalog(path: str | Path | None = None) -> PlanCatalog:
    """Load + validate the catalog. Raises CatalogInvalidError with all errors at once."""
    from synapse_saas.core.config import get_settings

    resolved = Path(path) if path is not None else Path(get_settings().plans_file)
    if not resolved.exists():
        raise CatalogInvalidError(f"Plans file not found: {resolved}", extras={"path": str(resolved)})
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogInvalidError(
            f"Plans file is not valid YAML: {exc}", extras={"path": str(resolved)}
        ) from exc
    try:
        return PlanCatalog.model_validate(raw)
    except CatalogInvalidError:
        raise
    except Exception as exc:  # pydantic ValidationError → catalog error with detail
        raise CatalogInvalidError(
            f"Plans file failed validation: {exc}",
            extras={"path": str(resolved)},
        ) from exc
