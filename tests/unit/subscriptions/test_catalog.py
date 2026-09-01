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
