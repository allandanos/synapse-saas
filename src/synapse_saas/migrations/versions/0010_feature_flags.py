"""feature_flags + feature_flag_overrides

Deployment-level toggles with org/user overrides and deterministic percentage
rollouts. Distinct from plan entitlements (billing).

Revision ID: 0010_feature_flags
Revises: 0009_stored_files
Create Date: 2026-09-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_feature_flags"
down_revision: Union[str, None] = "0009_stored_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "rollout_percentage",
            sa.Integer(),
            sa.CheckConstraint(
                "rollout_percentage IS NULL OR (rollout_percentage BETWEEN 0 AND 100)",
                name="ck_feature_flags_rollout",
            ),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "feature_flag_overrides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "flag_key",
            sa.String(100),
            sa.ForeignKey("feature_flags.key", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            index=True,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "organization_id IS NOT NULL OR user_id IS NOT NULL",
            name="ck_ff_override_scope",
        ),
    )


def downgrade() -> None:
    op.drop_table("feature_flag_overrides")
    op.drop_table("feature_flags")
