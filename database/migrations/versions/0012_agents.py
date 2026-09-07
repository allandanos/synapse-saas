"""agents registry + pgvector enablement

Org-scoped agent registry (governance/billing only — see ADR 0007: this
framework does not execute agents). Config is opaque JSON owned by whichever
runtime executes the agent. pgvector enabled per the long-documented Phase 4
prep so agent knowledge/memory storage never needs a coordinated enable.

Revision ID: 0012_agents
Revises: 0011_invoice_lines
Create Date: 2026-09-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_agents"
down_revision: Union[str, None] = "0011_invoice_lines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "status",
            sa.String(16),
            sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_agents_status"),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        # Opaque to this framework: model, system-prompt refs, tool allowlists —
        # the executing runtime owns the schema. Stored as-is, returned as-is.
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "slug", name="uq_agents_org_slug"),
    )
    op.create_index("ix_agents_org_status", "agents", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_agents_org_status", table_name="agents")
    op.drop_table("agents")
    op.execute("DROP EXTENSION IF EXISTS vector")
