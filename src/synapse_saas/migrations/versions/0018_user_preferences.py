"""users.preferences: a per-user JSONB store for console UI state.

`PATCH /v1/auth/me` merges top-level keys into it (first use: the console's
product-tour completion record). Users are not tenant-scoped, so no RLS
policy; no index (read by primary key only); existing rows get `{}`.

Revision ID: 0018_user_preferences
Revises: 0017_presigned_uploads
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0018_user_preferences"
down_revision: Union[str, None] = "0017_presigned_uploads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferences", JSONB(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("users", "preferences")
