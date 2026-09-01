# ADR-0002: App-level tenant isolation, optional RLS

Date: 2026-08-31
Status: Accepted

## Context

Multi-tenant Postgres offers two isolation strategies: application-level
filtering (every query scoped by the active tenant) or Postgres row-level
security driven by a session setting. The framework must run with the least
privilege friction while remaining a real security boundary.

## Decision

`TenantRepository` auto-filtering is the primary boundary. `SYNAPSE_TENANT_ISOLATION=app_and_rls`
optionally enables RLS policies (migration 0004) keyed off a
transaction-local `app.current_tenant` set by the session dependency.

Cross-tenant failures return 404 with a body identical to a nonexistent org —
never 403, which would leak existence.

## Consequences

+ Works under PgBouncer transaction pooling and serverless drivers where
  session-level `SET` semantics are messy
+ The isolation guarantee is testable in pytest rather than depending on DB
  role setup (pinned by `test_tenant_isolation.py` + `test_repository_isolation.py`)
+ Clone-and-run works with no DB superuser steps
− A code path that bypasses `TenantRepository` is unguarded unless RLS is on —
  hence opt-in RLS as defense-in-depth, recommended in production
