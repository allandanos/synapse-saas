"""example_projects table for examples/hello-saas

The hello-saas example's own table — included so the example runs against the
same database without manual DDL. Real domain apps own their migrations the
same way.

Revision ID: 0007_example_projects
Revises: 0006_webhook_constraints
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_example_projects"
down_revision: Union[str, None] = "0006_webhook_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "example_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("example_projects")
