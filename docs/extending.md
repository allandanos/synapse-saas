# Extending the framework

Two supported extension models. Pick by where your domain code wants to live;
both get the full tenancy/entitlement/usage machinery.

| | In-process extension | Domain service |
|---|---|---|
| Languages | **Python only** | **Any** (Go, Java, TypeScript, Python, …) |
| Your code lives | inside the framework process — ORM models + routers | its own service, own deployment, own lifecycle |
| Tenancy via | `TenantMixin` + `TenantRepository` (auto-scoped, in-process) | org API key + SDK calls (server-to-server) |
| Best for | products built *on* the framework in one deployable | polyglot products, existing services, teams per language |
| Example | [`examples/python/hello-saas`](../examples/python/hello-saas/) | [`examples/*/domain-service`](../examples/) |

## Model 1 — In-process extension (Python)

Your domain code imports framework primitives directly. This is the "your
application becomes incredibly small" model:

```python
from synapse_saas.core.db import Base, TenantMixin
from synapse_saas.core.repository import TenantRepository
from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.entitlements.dependencies import require_feature

class Project(TenantMixin, Base):          # org-scoped by inheritance
    __tablename__ = "projects"
    title: Mapped[str]

class ProjectRepo(TenantRepository[Project]):
    model = Project

@router.get("/projects")
async def list_projects(
    repo: ProjectRepo = Depends(...),
    _f=Depends(require_feature("api_access")),
):
    return await repo.list()               # WHERE organization_id = tenant — automatic
```

What you inherit: tenant auto-scoping (reads filtered, writes stamped, cross-
tenant = 404), permission/feature gates as dependencies, atomic usage
enforcement, audit + outbox on your mutations, and the full middleware stack.

**Limits of this model**: it's Python-only by construction — the primitives
are Python classes, SQLAlchemy models, and FastAPI dependencies. A Go or Java
service cannot import `TenantMixin`. That's what model 2 is for.

## Model 2 — Domain service (any language)

Your service owns its domain endpoints; tenancy decisions are delegated to
the framework API over the network using an **org API key** (`sk_…`). The
key authenticates *as the org*: tenant pinned server-side, scopes optional,
`api_requests` metered automatically on every call.

The pattern, per request:

```
client ──your auth──▶ your service ──org API key──▶ Synapse API
                       │
                       │  1. gate:    entitlements.effective() → feature present?
                       │              (403 + upgrade hints to the client)
                       │  2. meter:   usage.consume(metric, qty) → within quota?
                       │              (402 + metric/limit/upgrade_url to the client)
                       └─ 3. work:    do the domain thing
```

Reference implementations: [`examples/go/domain-service`](../examples/go/domain-service/),
[`examples/java/domain-service`](../examples/java/domain-service/),
[`examples/typescript/domain-service`](../examples/typescript/domain-service/),
[`examples/python/domain-service`](../examples/python/domain-service/) (Python
without framework imports — same model, for when you want the isolation).

### Rules of the pattern

1. **The API key is the service's credential, not the user's.** One key per
   org (or per service×org), created by an org admin, scoped to what the
   service needs (`scopes: ["usage:read"]` etc. — empty = full access).
   Rotate via the console; the old key dies immediately.

2. **Gate before you work, meter before you spend.** Both checks are cheap
   SDK calls. `consume` is atomic server-side: under concurrent requests,
   exactly the quota passes and the rest get typed 402s — check the
   metered-run example log in the example READMEs.

3. **Map framework errors to your product's errors.** The SDKs expose typed
   exceptions (`SynapseLimitError`/`LimitError`/`LimitException` with
   `metric`+`limit`, feature-gate errors with `available_in`). Translate to
   your own error envelope so clients see one API surface.

4. **Your service authenticates its own clients however it wants.** The
   examples use a shared bearer token for clarity; real products forward
   their own user sessions or issue their own tokens. The framework never
   sees your end users in this model — only the org.

### What you get vs. model 1

Everything the API can express — entitlements, limits, metering, plan
changes, invoices, webhooks — but **not** in-process ORM tenancy. Your
service's own data store is yours to scope: either keep a `organization_id`
column discipline yourself, or store per-tenant data in the framework's file
storage (org-scoped keys) and reference by id.

### Polyglot plugin protocol (not built)

A third model — non-Python services registering routes into the gateway with
shared tenant-context propagation (gRPC header forwarding, plugin manifests) —
is deliberately **not** built. It's a significant architectural addition and
sits with Phase 4+ scope. Model 2 covers today's real need: your Go/Java/
TypeScript product fully participates in plans, entitlements, and usage.

## Deciding

- Building a new product on the stack, Python backend? → **Model 1**; the
  domain app is ~50 lines (hello-saas).
- Existing Go/Java/TS service, polyglot team, or separate deploy cadence?
  → **Model 2**; the domain-service examples are copy-paste starters.
- Both? Common: console/billing on the framework (model 1), domain worker
  services per language (model 2). The org API key ties them to the same
  tenant, plan, and meters.
