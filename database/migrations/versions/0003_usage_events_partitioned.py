"""usage_events: monthly range-partitioned event ledger

Raw usage events are high-volume append-only rows; monthly partitions keep
indexes small and make retention (drop partition) instant. The worker's
`ensure_partitions` job pre-creates future partitions.

Revision ID: 0003_usage_events
Revises: 0002_framework_schema
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_usage_events"
down_revision: Union[str, None] = "0002_framework_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE usage_events (
            id              UUID            NOT NULL,
            organization_id UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            metric          VARCHAR(100)    NOT NULL REFERENCES metrics(key),
            quantity        BIGINT          NOT NULL DEFAULT 1,
            occurred_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            idempotency_key TEXT,
            properties      JSONB           NOT NULL DEFAULT '{}',
            recorded_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_usage_events_org_metric_time ON usage_events (organization_id, metric, occurred_at)"
    )
    op.execute("CREATE INDEX ix_usage_events_occurred_brin ON usage_events USING brin (occurred_at)")
    # Idempotency: (org, metric, key) unique while set. occurred_at is included
    # because Postgres requires partition columns in partitioned unique indexes;
    # consumers treat a key as single-use, so one landing instant is the contract.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_usage_events_idempotency
        ON usage_events (organization_id, metric, idempotency_key, occurred_at)
        WHERE idempotency_key IS NOT NULL
        """
    )
    # Bootstrap: current + next month partitions (worker keeps it rolling)
    op.execute(
        """
        DO $$
        DECLARE
            m DATE := date_trunc('month', now())::date;
            p DATE;
        BEGIN
            FOR i IN 0..1 LOOP
                p := (m + (i || ' months')::interval)::date;
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS usage_events_y%sm%s PARTITION OF usage_events FOR VALUES FROM (%L) TO (%L)',
                    to_char(p, 'YYYY'), to_char(p, 'MM'), p, p + INTERVAL '1 month'
                );
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events CASCADE")
