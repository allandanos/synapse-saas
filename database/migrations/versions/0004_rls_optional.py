"""optional row-level security (defense-in-depth)

Creates RLS policies on every organization-scoped table, keyed off the
transaction-local setting `app.current_tenant` (set by the session dependency
when SYNAPSE_TENANT_ISOLATION=app_and_rls). Application-level filtering via
TenantRepository remains the primary boundary; RLS catches what a code slip
would otherwise leak.

Revision ID: 0004_rls_optional
Revises: 0003_usage_events
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004_rls_optional"
down_revision: Union[str, None] = "0003_usage_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# organization_id is NULL-able on some tables (platform-scope rows) — those
# policies allow NULL rows through, matching the app-level semantics.
TENANT_TABLES = (
    "memberships",
    "roles",
    "audit_logs",
    "entitlements",
    "subscriptions",
    "billing_customers",
    "invoices",
    "usage_events",
    "webhook_endpoints",
    "webhook_deliveries",
)

NULLABLE_TENANT_TABLES = ("roles", "audit_logs", "webhook_deliveries")


def upgrade() -> None:
    # Table owner bypasses RLS by default; force it so the app role is bound.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        nullable = " OR organization_id IS NULL" if table in NULLABLE_TENANT_TABLES else ""
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (
                organization_id = CURRENT_SETTING('app.current_tenant', true)::uuid{nullable}
            )
            WITH CHECK (
                organization_id = CURRENT_SETTING('app.current_tenant', true)::uuid{nullable}
            )
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
