"""api keys: empty scopes no longer mean "everything" — snapshot the creator's permissions

Before, an API key with `scopes = {}` passed every permission check regardless
of what its creator could do (a developer-role user could mint an org:delete
key). Keys are now bounded by their creator at creation (subset check, empty
⇒ snapshot) and at auth (intersection with the creator's current permissions).

This backfills existing empty-scope keys from the creator's active membership
(`memberships.permission_keys` is the denormalized RBAC set). Keys whose
creator has no active membership keep `{}` and are therefore denied every
permission from now on — the safe default.

Revision ID: 0014_api_key_scope_snapshot
Revises: 0013_rls_rework
Create Date: 2026-09-28
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0014_api_key_scope_snapshot"
down_revision: Union[str, None] = "0013_rls_rework"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE api_keys k
        SET scopes = m.permission_keys
        FROM memberships m
        WHERE m.user_id = k.created_by_user_id
          AND m.organization_id = k.organization_id
          AND m.status = 'active'
          AND cardinality(k.scopes) = 0
          AND cardinality(m.permission_keys) > 0
        """
    )


def downgrade() -> None:
    # Irreversible by design: we cannot know which keys were originally empty.
    pass
