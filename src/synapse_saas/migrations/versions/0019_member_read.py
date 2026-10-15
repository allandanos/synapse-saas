"""member role gains member:read — a plain member can read the member list.

The console hides nav items the viewer lacks permission for, keyed on the new
`permission_keys` that `GET /v1/auth/me` returns per org. A `member` should see
who else is in the org, so the system `member` role is granted `member:read`
(side effect: `GET /v1/roles` shares that gate, so members can read the role
catalog too).

System roles are global rows and `seed_system` is append-only on
`role_permissions` and never recomputes `memberships.permission_keys`, so this
migration inserts the grant itself (idempotent; no-op on an empty database,
where the seed adds it) and recomputes the denormalised set for every
membership holding the system `member` role, mirroring
`AuthorizationService.recompute_membership_permissions`: the sorted union of
every role the membership holds (a member with a custom role keeps the union).
Downgrade revokes the grant and recomputes the same memberships.

Revision ID: 0019_member_read
Revises: 0018_user_preferences
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0019_member_read"
down_revision: Union[str, None] = "0018_user_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRANT = """
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
WHERE r.key = 'member' AND r.is_system AND r.organization_id IS NULL AND p.key = 'member:read'
ON CONFLICT DO NOTHING
"""

_REVOKE = """
DELETE FROM role_permissions rp USING roles r, permissions p
WHERE rp.role_id = r.id AND rp.permission_id = p.id
  AND r.key = 'member' AND r.is_system AND r.organization_id IS NULL AND p.key = 'member:read'
"""

# Sorted union of every role the membership holds; COLLATE "C" = Python sorted() order.
# DISTINCT lives in the subquery: Postgres rejects array_agg(DISTINCT x ORDER BY x COLLATE "C").
# permissions.key is varchar; cast to text so the aggregate compares with the text[] column.
_RECOMPUTE_MEMBER_HOLDERS = """
UPDATE memberships m SET permission_keys = agg.keys
FROM (
  SELECT d.membership_id, array_agg(d.key ORDER BY d.key COLLATE "C") AS keys
  FROM (SELECT DISTINCT mr.membership_id, p.key::text AS key
        FROM membership_roles mr
        JOIN role_permissions rp ON rp.role_id = mr.role_id
        JOIN permissions p ON p.id = rp.permission_id) d
  GROUP BY d.membership_id
) agg
WHERE m.id = agg.membership_id
  AND m.id IN (SELECT mr2.membership_id FROM membership_roles mr2
               JOIN roles r ON r.id = mr2.role_id
               WHERE r.key = 'member' AND r.is_system AND r.organization_id IS NULL)
  AND m.permission_keys IS DISTINCT FROM agg.keys
"""


def upgrade() -> None:
    op.execute(_GRANT)
    op.execute(_RECOMPUTE_MEMBER_HOLDERS)


def downgrade() -> None:
    op.execute(_REVOKE)
    op.execute(_RECOMPUTE_MEMBER_HOLDERS)
