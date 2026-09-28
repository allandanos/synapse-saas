"""billing integrity (P2 / WS-B).

- usage_idempotency_keys: a true dedupe ledger for `idempotency_key`. The old
  partial index on usage_events had to include the partition key, so retries
  double-counted. This table is not partitioned, so (org, key) is unique.
- subscriptions.pending_adjustments: prorated credits/charges from mid-period
  plan changes, drained into the next drafted invoice.
- entitlements.limit_value: `limit:<metric>` grants stop encoding their value
  in the free-text `note` column; backfilled from `limit=<n>` notes.
- plan_limits / metrics overage_unit + overage_price_cents: overage pricing
  comes from the catalog (per metric default, per-plan override) instead of a
  constant in code.
- usage gauges (users, projects, storage_bytes) move to a fixed 1970-01-01
  counter bucket that never resets; today's levels are seeded from the tables.
- invoices: (organization_id, number) unique — numbering races surface as a
  constraint error instead of a duplicate invoice number.

Revision ID: 0015_billing_integrity
Revises: 0014_api_key_scope_snapshot
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_billing_integrity"
down_revision: Union[str, None] = "0014_api_key_scope_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_GUC = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
PLATFORM_GUC = "current_setting('app.rls_platform', true) = 'on'"
IDEMPOTENCY_PREDICATE = f"organization_id = {TENANT_GUC} OR {PLATFORM_GUC}"


def upgrade() -> None:
    # ── usage idempotency ledger ──────────────────────────────────────────────
    op.create_table(
        "usage_idempotency_keys",
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("total_after", sa.BigInteger(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("organization_id", "idempotency_key", name="pk_usage_idempotency_keys"),
    )
    op.create_index(
        "ix_usage_idempotency_keys_organization_id", "usage_idempotency_keys", ["organization_id"]
    )
    op.create_index("ix_usage_idempotency_keys_created_at", "usage_idempotency_keys", ["created_at"])
    op.execute("ALTER TABLE usage_idempotency_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE usage_idempotency_keys NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON usage_idempotency_keys
        USING ({IDEMPOTENCY_PREDICATE})
        WITH CHECK ({IDEMPOTENCY_PREDICATE})
        """
    )

    # ── prorated adjustments drained by the next invoice draft ────────────────
    op.add_column(
        "subscriptions",
        sa.Column(
            "pending_adjustments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    # ── limit grants carry a real column ──────────────────────────────────────
    op.add_column("entitlements", sa.Column("limit_value", sa.BigInteger(), nullable=True))
    op.execute(
        r"""
        UPDATE entitlements
        SET limit_value = substring(note FROM '^limit=(\d+)$')::bigint
        WHERE note ~ '^limit=\d+$' AND limit_value IS NULL
        """
    )

    # ── catalog-driven overage pricing ────────────────────────────────────────
    op.add_column("plan_limits", sa.Column("overage_unit", sa.Integer(), nullable=True))
    op.add_column("plan_limits", sa.Column("overage_price_cents", sa.BigInteger(), nullable=True))
    # Metric-level default: what an addon-created limit (limit:<metric> grant on a
    # plan that never limited the metric) bills overage at.
    op.add_column("metrics", sa.Column("overage_unit", sa.Integer(), nullable=True))
    op.add_column("metrics", sa.Column("overage_price_cents", sa.BigInteger(), nullable=True))

    # ── gauges live in a fixed bucket; seed today's levels ────────────────────
    # (`storage_bytes` becomes a gauge in the catalog; `users`/`projects` always were)
    op.execute(
        """
        INSERT INTO usage_counters (organization_id, metric, period_start, quantity_total, last_event_at)
        SELECT organization_id, 'storage_bytes', DATE '1970-01-01', COALESCE(SUM(size_bytes), 0), now()
        FROM stored_files WHERE deleted_at IS NULL GROUP BY organization_id
        ON CONFLICT (organization_id, metric, period_start)
        DO UPDATE SET quantity_total = EXCLUDED.quantity_total, last_event_at = now()
        """
    )
    op.execute(
        """
        INSERT INTO usage_counters (organization_id, metric, period_start, quantity_total, last_event_at)
        SELECT organization_id, 'users', DATE '1970-01-01', COUNT(*), now()
        FROM memberships WHERE status IN ('active', 'invited') GROUP BY organization_id
        ON CONFLICT (organization_id, metric, period_start)
        DO UPDATE SET quantity_total = EXCLUDED.quantity_total, last_event_at = now()
        """
    )
    op.execute(
        """
        INSERT INTO usage_counters (organization_id, metric, period_start, quantity_total, last_event_at)
        SELECT organization_id, 'projects', DATE '1970-01-01', COUNT(*), now()
        FROM example_projects GROUP BY organization_id
        ON CONFLICT (organization_id, metric, period_start)
        DO UPDATE SET quantity_total = EXCLUDED.quantity_total, last_event_at = now()
        """
    )

    # ── invoice numbers are unique per org ────────────────────────────────────
    op.create_index(
        "uq_invoices_org_number",
        "invoices",
        ["organization_id", "number"],
        unique=True,
        postgresql_where=sa.text("number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_invoices_org_number", table_name="invoices")
    op.execute("DELETE FROM usage_counters WHERE period_start = DATE '1970-01-01'")
    op.drop_column("metrics", "overage_price_cents")
    op.drop_column("metrics", "overage_unit")
    op.drop_column("plan_limits", "overage_price_cents")
    op.drop_column("plan_limits", "overage_unit")
    # Fold the value back into the note so 0014-era code keeps resolving it
    op.execute(
        """
        UPDATE entitlements
        SET note = 'limit=' || limit_value::text
        WHERE limit_value IS NOT NULL AND feature_key LIKE 'limit:%'
        """
    )
    op.drop_column("entitlements", "limit_value")
    op.drop_column("subscriptions", "pending_adjustments")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON usage_idempotency_keys")
    op.drop_index("ix_usage_idempotency_keys_created_at", table_name="usage_idempotency_keys")
    op.drop_index("ix_usage_idempotency_keys_organization_id", table_name="usage_idempotency_keys")
    op.drop_table("usage_idempotency_keys")
