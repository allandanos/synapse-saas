"""Catalog loading + validation unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from synapse_saas.core.errors import CatalogInvalidError
from synapse_saas.subscriptions.catalog import load_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]
PLANS_FILE = REPO_ROOT / "config" / "plans.yaml"


class TestShippedCatalog:
    def test_loads_and_validates(self) -> None:
        catalog = load_catalog(PLANS_FILE)
        assert len(catalog.plans) >= 4

    def test_plan_keys(self) -> None:
        catalog = load_catalog(PLANS_FILE)
        assert {p.key for p in catalog.plans} >= {"free", "starter", "pro", "enterprise"}

    def test_prices_are_integer_minor_units(self) -> None:
        catalog = load_catalog(PLANS_FILE)
        by_key = {p.key: p for p in catalog.plans}
        assert by_key["free"].price_cents == 0
        assert by_key["starter"].price_cents == 49900  # ₱499.00
        assert by_key["pro"].price_cents == 199900  # ₱1,999.00
        assert by_key["enterprise"].price == "custom"

    def test_enterprise_not_public(self) -> None:
        catalog = load_catalog(PLANS_FILE)
        enterprise = catalog.plan("enterprise")
        assert enterprise is not None and not enterprise.is_public

    def test_unlimited_limits_are_none(self) -> None:
        catalog = load_catalog(PLANS_FILE)
        pro = catalog.plan("pro")
        assert pro is not None and pro.limits["projects"] is None


class TestValidationFailures:
    def _write(self, tmp_path: Path, content: str) -> Path:
        path = tmp_path / "plans.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_unknown_feature_rejected(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - key: pro
    name: Pro
    price_cents: 100
    features: [nonexistent_feature]
""",
        )
        with pytest.raises(CatalogInvalidError) as exc:
            load_catalog(path)
        assert "nonexistent_feature" in str(exc.value.extras.get("errors"))

    def test_unknown_metric_in_limits(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - key: pro
    name: Pro
    price_cents: 100
    limits: {warp_drives: 5}
""",
        )
        with pytest.raises(CatalogInvalidError) as exc:
            load_catalog(path)
        assert "warp_drives" in str(exc.value.extras.get("errors"))

    def test_duplicate_plan_keys(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - {key: pro, name: Pro, price_cents: 100}
  - {key: pro, name: Pro Again, price_cents: 200}
""",
        )
        with pytest.raises(CatalogInvalidError) as exc:
            load_catalog(path)
        assert "duplicate plan" in str(exc.value.extras.get("errors"))

    def test_price_cents_and_custom_both_set(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - {key: pro, name: Pro, price_cents: 100, price: custom}
""",
        )
        with pytest.raises(CatalogInvalidError):
            load_catalog(path)

    def test_missing_price_rejected(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - {key: pro, name: Pro}
""",
        )
        with pytest.raises(CatalogInvalidError):
            load_catalog(path)

    def test_public_plan_requires_concrete_price(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - {key: pro, name: Pro, price: custom, is_public: true, is_custom: true}
""",
        )
        with pytest.raises(CatalogInvalidError) as exc:
            load_catalog(path)
        assert "concrete price" in str(exc.value.extras.get("errors"))

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(CatalogInvalidError, match="not found"):
            load_catalog(tmp_path / "nope.yaml")

    def test_malformed_yaml(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, "version: [unclosed")
        with pytest.raises(CatalogInvalidError, match="not valid YAML"):
            load_catalog(path)

    def test_all_errors_reported_at_once(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            """
version: 1
features: [{key: basic_dashboard, name: Basic}]
metrics: [{key: users, name: Users, kind: gauge}]
plans:
  - {key: pro, name: Pro, price_cents: 100, features: [ghost], limits: {phantom: 1}}
  - {key: pro, name: Dup, price_cents: 200}
""",
        )
        with pytest.raises(CatalogInvalidError) as exc:
            load_catalog(path)
        errors = str(exc.value.extras.get("errors"))
        assert "ghost" in errors and "phantom" in errors and "duplicate plan" in errors


# ── Overage pricing in the catalog ────────────────────────────────────────────


def _catalog(**overrides: object) -> dict:
    base: dict = {
        "version": 1,
        "features": [{"key": "f", "name": "F"}],
        "metrics": [
            {
                "key": "ai_tokens",
                "name": "AI",
                "kind": "counter",
                "overage": {"unit": 1000, "price_cents": 20},
            },
            {"key": "seats", "name": "Seats", "kind": "gauge"},
        ],
        "plans": [
            {"key": "starter", "name": "S", "price_cents": 100, "limits": {"ai_tokens": 10}},
            {
                "key": "pro",
                "name": "P",
                "price_cents": 200,
                "limits": {"ai_tokens": 100, "seats": 5},
                "overage": {"ai_tokens": {"unit": 1000, "price_cents": 15}},
            },
        ],
    }
    base.update(overrides)
    return base


class TestOverageCatalog:
    def test_plan_override_beats_metric_default(self) -> None:
        from synapse_saas.subscriptions.catalog import PlanCatalog

        catalog = PlanCatalog.model_validate(_catalog())
        assert catalog.overage_for("starter", "ai_tokens").price_cents == 20  # type: ignore[union-attr]
        assert catalog.overage_for("pro", "ai_tokens").price_cents == 15  # type: ignore[union-attr]
        assert catalog.overage_for("pro", "seats") is None  # unpriced ⇒ enforced, never billed

    def test_overage_for_an_unlimited_metric_is_rejected(self) -> None:
        import pytest

        from synapse_saas.core.errors import CatalogInvalidError
        from synapse_saas.subscriptions.catalog import PlanCatalog

        bad = _catalog()
        bad["plans"][0]["overage"] = {"seats": {"unit": 1, "price_cents": 5}}  # starter never limits seats
        with pytest.raises(CatalogInvalidError) as excinfo:
            PlanCatalog.model_validate(bad)
        assert "prices overage for metrics it does not limit" in str(excinfo.value.extras)

    def test_unit_must_be_positive(self) -> None:
        import pytest
        from pydantic import ValidationError

        from synapse_saas.subscriptions.catalog import PlanCatalog

        bad = _catalog()
        bad["metrics"][0]["overage"] = {"unit": 0, "price_cents": 20}
        with pytest.raises(ValidationError):
            PlanCatalog.model_validate(bad)
