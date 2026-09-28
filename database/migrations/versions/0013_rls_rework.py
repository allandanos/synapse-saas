"""row-level security rework: complete policy set, role-bound enforcement

Replaces 0004's policies. What changed and why:

- 0004 FORCEd RLS on 10 tables keyed on `app.current_tenant`, but nothing
  ever set that GUC and the table list stopped at Phase 1. A non-superuser
  app role saw zero rows; the superuser dev role saw everything. Neither was
  the documented behaviour.
- Enforcement is now bound to the CONNECTION ROLE, not FORCE: the API
  connects as a non-owner role (see `synapse-cli db provision-app-role`) and
  is subject to policies; the worker, CLI, and migrations connect as the
  schema owner and bypass them (NO FORCE). The API sets three GUCs per
  request: `app.current_user` after authentication, `app.current_tenant`
  after tenant resolution, `app.rls_platform=on` on platform-admin surfaces.
- Every organization-scoped table gets a policy (18 tables). Two credential
  tables are deliberately excluded and documented: `api_keys` and
  `refresh_tokens` are looked up by secret hash BEFORE any tenant context
  exists; the hash is the authorization.
- `invoice_lines` gains `organization_id` (backfilled from invoices) so it can
  be policed without a subquery policy.
- Two lookups legitimately happen BEFORE the tenant is known — invite
  acceptance (by token hash; an invited membership has user_id NULL) and
  billing-webhook apply (by provider customer/subscription id). Each gets a
  narrow SECURITY DEFINER function that returns only the organization id,
  after which the caller binds the tenant GUC and proceeds under policy.

Revision ID: 0013_rls_rework
Revises: 0012_agents
Create Date: 2026-09-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_rls_rework"
down_revision: Union[str, None] = "0012_agents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> (organization_id nullable, user-scoped rows allowed via app.current_user)
TENANT_POLICIES: dict[str, tuple[bool, bool]] = {
    "agents": (False, False),
    "audit_logs": (True, False),
    "billing_customers": (False, False),
    "entitlements": (False, False),
    "example_projects": (False, False),
    "feature_flag_overrides": (True, True),
    "invoice_lines": (False, False),
    "invoices": (False, False),
    "memberships": (False, True),
    "outbox_events": (True, False),
    "roles": (True, False),
    "stored_files": (False, False),
    "subscriptions": (False, False),
    "usage_counters": (False, False),
    "usage_events": (False, False),
    "webhook_deliveries": (False, False),
    "webhook_endpoints": (False, False),
}

# Looked up by secret hash before tenant context exists; the hash IS the authz.
RLS_EXCLUDED: tuple[str, ...] = ("api_keys", "refresh_tokens")

# 0004's set, restored on downgrade
LEGACY_TABLES = (
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
LEGACY_NULLABLE = ("roles", "audit_logs", "webhook_deliveries")

TENANT_GUC = "NULLIF(current_setting('app.current_tenant', true), '')::uuid"
USER_GUC = "NULLIF(current_setting('app.current_user', true), '')::uuid"
PLATFORM_GUC = "current_setting('app.rls_platform', true) = 'on'"


def _predicate(nullable_org: bool, user_scoped: bool) -> str:
    clauses = [f"organization_id = {TENANT_GUC}", PLATFORM_GUC]
    if nullable_org:
        clauses.append("organization_id IS NULL")
    if user_scoped:
        clauses.append(f"user_id = {USER_GUC}")
    return " OR ".join(clauses)


LOOKUP_FUNCTIONS = (
    # invite token hash -> organization (memberships.invite_token_hash is unique-ish per org)
    """
    CREATE OR REPLACE FUNCTION synapse_org_for_invite_token(p_hash text)
    RETURNS uuid
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = public
    STABLE
    AS $$
        SELECT organization_id FROM memberships
        WHERE invite_token_hash = p_hash AND status = 'invited'
        LIMIT 1
    $$
    """,
    # provider references -> organization (billing webhooks arrive unauthenticated)
    """
    CREATE OR REPLACE FUNCTION synapse_org_for_provider_ref(p_customer_id text, p_subscription_id text)
    RETURNS uuid
    LANGUAGE sql
    SECURITY DEFINER
    SET search_path = public
    STABLE
    AS $$
        SELECT organization_id FROM (
            SELECT organization_id, 1 AS rank FROM billing_customers
            WHERE p_customer_id IS NOT NULL AND provider_customer_id = p_customer_id
            UNION ALL
            SELECT organization_id, 2 FROM subscriptions
            WHERE p_subscription_id IS NOT NULL AND provider_subscription_id = p_subscription_id
        ) refs
        ORDER BY rank
        LIMIT 1
    $$
    """,
)


def upgrade() -> None:
    for ddl in LOOKUP_FUNCTIONS:
        op.execute(ddl)

    # invoice_lines: add the tenant column so it can be policed directly
    op.add_column("invoice_lines", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE invoice_lines il
        SET organization_id = i.organization_id
        FROM invoices i
        WHERE il.invoice_id = i.id AND il.organization_id IS NULL
        """
    )
    op.alter_column("invoice_lines", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_invoice_lines_organization_id_organizations",
        "invoice_lines",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_invoice_lines_organization_id", "invoice_lines", ["organization_id"])

    for table, (nullable_org, user_scoped) in TENANT_POLICIES.items():
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # NO FORCE: the owner (worker/CLI/migrations) bypasses; the app role does not.
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        predicate = _predicate(nullable_org, user_scoped)
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING ({predicate})
            WITH CHECK ({predicate})
            """
        )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS synapse_org_for_invite_token(text)")
    op.execute("DROP FUNCTION IF EXISTS synapse_org_for_provider_ref(text, text)")

    for table in TENANT_POLICIES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Restore 0004's (forced, GUC-only) policies on its original table set
    for table in LEGACY_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        nullable = " OR organization_id IS NULL" if table in LEGACY_NULLABLE else ""
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (organization_id = CURRENT_SETTING('app.current_tenant', true)::uuid{nullable})
            WITH CHECK (organization_id = CURRENT_SETTING('app.current_tenant', true)::uuid{nullable})
            """
        )

    op.drop_index("ix_invoice_lines_organization_id", table_name="invoice_lines")
    op.drop_constraint("fk_invoice_lines_organization_id_organizations", "invoice_lines", type_="foreignkey")
    op.drop_column("invoice_lines", "organization_id")
