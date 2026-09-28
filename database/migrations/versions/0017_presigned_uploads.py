"""stored_files.status for the presigned-upload flow (P4 / WS-F).

A presigned PUT creates the index row as `pending` (quota reserved); the
client uploads straight to the bucket and then calls `complete`, which
verifies the object and flips the row to `ready`. Pending rows past the
presign window are reclaimed by the retention job.

Revision ID: 0017_presigned_uploads
Revises: 0016_outbox_audience
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_presigned_uploads"
down_revision: Union[str, None] = "0016_outbox_audience"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stored_files",
        sa.Column("status", sa.String(16), server_default="ready", nullable=False),
    )
    op.create_check_constraint("ck_stored_files_status", "stored_files", "status IN ('pending', 'ready')")
    op.create_index(
        "ix_stored_files_pending",
        "stored_files",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_stored_files_pending", table_name="stored_files")
    op.drop_constraint("ck_stored_files_status", "stored_files", type_="check")
    op.drop_column("stored_files", "status")
