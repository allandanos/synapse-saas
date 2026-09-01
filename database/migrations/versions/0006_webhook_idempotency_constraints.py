"""webhook idempotency + invoice dedupe constraints

Adds the unique constraints webhook ingest relies on:
- provider_webhook_events (provider, provider_event_id) — replay protection
- invoices (provider, provider_invoice_id) — idempotent invoice upserts

Revision ID: 0006_webhook_constraints
Revises: 0005_membership_invite_tokens
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0006_webhook_constraints"
down_revision: Union[str, None] = "0005_membership_invite_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_webhook_events_ref
        ON provider_webhook_events (provider, provider_event_id)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_provider_ref
        ON invoices (provider, provider_invoice_id)
        WHERE provider_invoice_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_invoices_provider_ref")
    op.execute("DROP INDEX IF EXISTS uq_provider_webhook_events_ref")
