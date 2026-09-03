# Architecture

Synapse SaaS Framework is a single Python distribution plus a Next.js console.
Your product code depends on the framework modules; the framework never depends
on your product.

```
┌────────────────────┐
│  Next.js Console   │  apps/web — auth, orgs, billing, usage, audit UI
└─────────┬──────────┘
          │ REST /v1
┌─────────▼──────────┐
│  FastAPI (api)     │  routers → services → repositories
└─────────┬──────────┘
          │
   ┌──────┼─────────────────────────┐
   ▼      ▼                         ▼
tenancy  identity  authorization   subscriptions/entitlements/usage/billing
   └──────┴─────────────────────────┘
          │
┌─────────▼──────────┐     ┌──────────────┐
│  PostgreSQL        │     │ arq worker   │ outbox → webhooks, cron jobs
└────────────────────┘     └──────────────┘
```

## Layers

| Layer | File | Responsibility |
|---|---|---|
| Router | `*/router.py` | HTTP only: schemas, dependency wiring, status codes |
| Service | `*/service.py` | Domain logic; mutations write audit + outbox in the same transaction |
| Repository | `*/repository.py` | SQLAlchemy async queries only |
| Core | `core/*` | Context, DB, cache, errors, security — imported by everyone |

Import direction is enforced by import-linter: modules may import `core` and
their own package; only `api`/`worker` compose everything.

## Module map

| Module | Owns |
|---|---|
| `core` | config, tenant/user contextvars, DB engine + TenantRepository, caches, errors, security |
| `identity` | users, JWT access tokens, refresh rotation, Keycloak OIDC adapter |
| `tenancy` | organizations, memberships, invites, tenant resolution |
| `authorization` | roles, permissions, `require_permission` (OpenFGA seam) |
| `subscriptions` | plans, catalog YAML, sync, subscription state machine |
| `entitlements` | grant table + pure resolver → effective features/limits |
| `usage` | events (partitioned), counters, atomic limit enforcement |
| `billing` | BillingProvider protocol + 4 providers, customers, invoices, webhook ingest |
| `webhooks` | outbound endpoints + signed deliveries with backoff |
| `audit` | append-only log + outbox + provider event ledger |
| `worker` | arq cron jobs (dispatch, deliver, rollup, expire, purge) |

## Key invariants

1. **Tenant isolation** — `TenantRepository` filters every read and stamps every
   write. Cross-tenant access is a 404 identical to a phantom org. Opt-in
   Postgres RLS adds defense-in-depth.
2. **Transactional events** — audit rows and outbox events commit atomically
   with the state change they describe. A webhook delivery can never be lost to
   a crash between "save" and "publish".
3. **Idempotent webhook ingest** — `provider_webhook_events` has a unique
   (provider, event id); replays are 200 no-ops, never double-applied.
4. **Pricing is data** — plans/features/limits live in `config/plans.yaml`,
   validated at startup, synced to the DB. `plan_snapshot` freezes purchase
   terms so catalog edits never rewrite history.
5. **Money is integers** — minor units + ISO-4217; no floats anywhere.

## Request lifecycle

1. Middleware assigns/propagates `X-Request-Id`, binds structlog context
2. `get_current_user` decodes the JWT and binds `UserContext`
3. `resolve_tenant` resolves the org (`X-Org-Id`/`X-Org-Slug`/subdomain/JWT
   claim), verifies membership, binds `TenantContext`
4. `require_permission` checks RBAC (cached ~30s, invalidated on role changes)
5. The service runs; mutations append audit + outbox in-transaction
6. `get_session` commits; the worker later drains the outbox


## pgvector (Phase 4 prep)

The Postgres diagram in the original design includes pgvector for agent
knowledge/memory. The framework deliberately does not enable it yet — no
current table uses vectors — but the migration to do so is one line when
Phase 4 (Agentic) lands:

```python
# migration
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

Managed Postgres offerings (Cloud SQL, RDS, Supabase) all support it; nothing
in the current schema blocks it.
