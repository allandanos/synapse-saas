# Synapse SaaS Framework

[![CI](https://github.com/allandanos/synapse-saas/actions/workflows/ci.yml/badge.svg)](https://github.com/allandanos/synapse-saas/actions/workflows/ci.yml)

An open-source, multi-tenant SaaS framework: clone → define your domain → configure plans → deploy.

You get tenancy, identity, RBAC, audit, plans, entitlements, subscriptions, trials, usage metering,
billing, and webhooks — so your product code only contains your product.

```python
# Your domain model. That's it — tenant scoping is inherited.
from synapse_saas.core.db import Base, TenantMixin

class Project(TenantMixin, Base):
    title: Mapped[str]
```

```python
# Your router. Tenant resolution, auth, entitlements: framework.
@router.get("/projects")
async def list_projects(
    repo: ProjectRepo = Depends(project_repo),
    _feat=Depends(require_feature("api_access")),
):
    return await repo.list()   # WHERE organization_id = current tenant — automatic
```

## Quickstart

```bash
git clone https://github.com/allandanos/synapse-saas.git my-saas
cd my-saas
cp .env.example .env          # defaults work for local dev
docker compose up --build
```

| Service | URL |
|---|---|
| Web console | http://localhost:3000 |
| API + OpenAPI docs | http://localhost:8000/docs |
| PostgreSQL | localhost:5433 (`synapse`/`synapse`) |
| Redis | localhost:6380 |

The stack runs with the **Manual billing provider** — no Stripe/Xendit/PayMongo accounts needed.
Register a user, create an organization, and the full freemium loop (plans, limits, upgrade,
usage meters) works locally out of the box.

## What's inside

| Capability | Status |
|---|---|
| Multi-tenancy (orgs, tenant-scoped repositories, optional RLS) | ✅ Phase 1 |
| Auth rate limiting (per-IP + per-identity, Redis-backed) | ✅ |
| Identity (JWT + refresh rotation; Keycloak OIDC adapter) | ✅ Phase 1 |
| RBAC (system + custom roles, permission catalog) | ✅ Phase 1 |
| Audit log | ✅ Phase 1 |
| Plans-as-config (YAML catalog) | ✅ Phase 2 |
| Entitlements (trials, add-ons, overrides, grandfathering) | ✅ Phase 2 |
| Subscriptions + trials | ✅ Phase 2 |
| Usage metering (counters + gauges, soft/hard limits) | ✅ Phase 2 |
| Billing (Stripe, Xendit, PayMongo, Manual) | ✅ Phase 2 |
| API keys (scoped, hashed, metered) | ✅ Phase 3 |
| Email notifications (invites, password resets; SMTP via outbox) | ✅ Phase 3 |
| File storage (S3/R2/MinIO + local fallback, org-scoped keys, quota) | ✅ Phase 3 |
| Feature flags (org/user overrides, deterministic % rollout) | ✅ Phase 3 |
| Outbound webhooks (signed, retried) + transactional outbox | ✅ Phase 2 |
| Background jobs (arq worker) | ✅ Phase 2 |
| Notifications, storage, feature flags | 🔜 Phase 3 (interfaces only) |
| Admin console, SDKs, K8s/Terraform | 🔜 Phase 3+ |

## Plans are configuration, not code

`config/plans.yaml` is the pricing source of truth:

```yaml
plans:
  - key: starter
    price_cents: 49900        # ₱499.00 — integer minor units, never floats
    interval: month
    features: [basic_dashboard, api_access, reports, email_support]
    limits: { users: 10, projects: 20, api_requests: 100000 }
```

Application code asks the framework, never the plan name:

```python
entitlements.has("advanced_reports")   # False on Free, True on Pro, True during a trial
usage.within_limit("api_requests")     # checked against the effective, overridden limit
```

## Documentation

- [Architecture](docs/architecture.md)
- [Multi-tenancy](docs/multi-tenancy.md)
- [Plans & entitlements](docs/plans-and-entitlements.md)
- [Usage metering](docs/usage-metering.md)
- [Billing providers](docs/billing-providers.md)
- [Webhooks](docs/webhooks.md)
- [API reference](docs/api.md) (live: `/docs`)
- [ADRs](docs/adr/)

## Development

```bash
make install      # uv sync
make test         # unit tests
make test-pg      # integration tests (docker compose up -d postgres first)
make test-all     # everything, 80% coverage gate
make lint typecheck
```

## License

Apache-2.0 — see [LICENSE](LICENSE). The framework core stays genuinely useful without paying
anyone; that's the point.
