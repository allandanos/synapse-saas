"""membership invite tokens

Single-use hashed tokens for accepting invitations out-of-band (email links).

Revision ID: 0005_membership_invite_tokens
Revises: 0004_rls_optional
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_membership_invite_tokens"
down_revision: Union[str, None] = "0004_rls_optional"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memberships", sa.Column("invite_token_hash", sa.String(64)))
    op.create_index(
        op.f("ix_memberships_invite_token_hash"),
        "memberships",
        ["invite_token_hash"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_memberships_invite_token_hash"), table_name="memberships")
    op.drop_column("memberships", "invite_token_hash")
