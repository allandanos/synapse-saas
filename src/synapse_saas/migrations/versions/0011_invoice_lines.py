"""invoice_lines — line items on framework-generated invoices

Plan charge + metered overage lines built by the InvoicingService at draft
time. Provider-sourced invoices (webhook upserts) do not create lines.

Revision ID: 0011_invoice_lines
Revises: 0010_feature_flags
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_invoice_lines"
down_revision: Union[str, None] = "0010_feature_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.Uuid(),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("unit_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("metric", sa.String(100)),
        sa.Column("properties", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "kind IN ('plan','overage','credit','custom')",
            name="ck_invoice_lines_kind",
        ),
    )
    op.create_index(
        "ix_invoice_lines_kind",
        "invoice_lines",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoice_lines_kind", table_name="invoice_lines")
    op.drop_table("invoice_lines")
