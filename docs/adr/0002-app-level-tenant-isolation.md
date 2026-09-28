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
optionally enables RLS policies (migration 0004, reworked in 0013) keyed off
transaction-local settings the request binds as it learns them:
`app.current_user` at authentication, `app.current_tenant` at tenant
resolution, `app.rls_platform` on platform-admin surfaces. Enforcement is bound
to the connection role (API = NOBYPASSRLS subject role; worker/CLI/migrations =
owner), never to FORCE, and the API refuses to start if role and flag disagree.

Cross-tenant failures return 404 with a body identical to a nonexistent org —
never 403, which would leak existence.

## Consequences

+ Works under PgBouncer transaction pooling and serverless drivers where
  session-level `SET` semantics are messy
+ The isolation guarantee is testable in pytest rather than depending on DB
  role setup (pinned by `test_tenant_isolation.py` + `test_repository_isolation.py`)
+ Clone-and-run works with no DB superuser steps
− A code path that bypasses `TenantRepository` is unguarded unless RLS is on —
  hence opt-in RLS as defense-in-depth, recommended in production. Amended
  2026-09-28: the original wiring never set the GUC and FORCEd policies on a
  Phase-1 table list; migration 0013 + the three-GUC model above replace it
  (see docs/multi-tenancy.md).
