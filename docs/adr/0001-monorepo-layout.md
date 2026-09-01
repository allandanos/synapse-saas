# ADR-0001: Single-distribution monorepo

Date: 2026-08-31
Status: Accepted

## Context

The vision doc proposes `packages/{identity,tenancy,billing,…}` per concern.
Python has no npm-workspaces equivalent; the choices were a uv workspace of
many installable packages, or one src-layout distribution with internal module
boundaries.

## Decision

One distribution — `synapse-saas` — with `src/synapse_saas/<module>/` per
concern, plus `apps/web` (Next.js) and thin launchers in `apps/{api,worker}`.

Module boundaries are enforced with import-linter:
- modules may import `core` and their own package
- only `api`/`worker` compose everything
- `billing.providers.*` may import only `billing.protocol` + `core`

## Consequences

+ One Alembic history, one test suite, one version — the framework ships as a unit
+ Fast agent/repo navigation; no cross-package version skew or lock churn
+ A module's boundary already equals a package boundary, so extracting one
  later (e.g. a standalone `synapse-billing`) is mechanical
− Packaging does not *enforce* the boundaries; import-linter is advisory in
  tooling (accepted — CI runs it)

The prompt's `packages/*` concept maps 1:1 to `src/synapse_saas/*`; the mental
model survives, the packaging ceremony doesn't.
