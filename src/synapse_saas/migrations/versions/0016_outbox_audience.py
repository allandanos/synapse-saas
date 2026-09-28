"""outbox audience + dead-letter, default usage partition (P3 / WS-D).

- outbox_events.audience: 'public' events fan out to tenant webhook endpoints;
  'internal' events (invite emails carrying tokens, password-reset links,
  invoice emails) are consumed in-process only. Before this, `member.invited`
  shipped the plaintext invite token to every webhook endpoint of the org.
- outbox_events.dead_at: events that failed OUTBOX_MAX_ATTEMPTS times leave
  the dispatch loop instead of retrying the same batch every 5 seconds forever.
- usage_events_default: a DEFAULT partition so a lapsed partition-creation cron
  degrades to slower inserts instead of every record/consume failing.

Revision ID: 0016_outbox_audience
Revises: 0015_billing_integrity
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_outbox_audience"
down_revision: Union[str, None] = "0015_billing_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INTERNAL_EVENT_TYPES = ("invoice.email", "user.password_reset_link", "member.invite_email")


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("audience", sa.String(16), server_default="public", nullable=False),
    )
    op.add_column("outbox_events", sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_outbox_events_audience", "outbox_events", "audience IN ('public', 'internal')"
    )
    # Existing unpublished internal events must not fan out once dispatch resumes
    op.execute(
        "UPDATE outbox_events SET audience = 'internal' WHERE event_type IN ("
        + ", ".join(f"'{e}'" for e in INTERNAL_EVENT_TYPES)
        + ")"
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("published_at IS NULL AND dead_at IS NULL"),
    )
    op.execute("CREATE TABLE IF NOT EXISTS usage_events_default PARTITION OF usage_events DEFAULT")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events_default")
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
    op.drop_constraint("ck_outbox_events_audience", "outbox_events", type_="check")
    op.drop_column("outbox_events", "dead_at")
    op.drop_column("outbox_events", "audience")
