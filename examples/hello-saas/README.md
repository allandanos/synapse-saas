# hello-saas — your first domain app on the framework

This example proves the framework's core promise: **your product code contains
only your product.** A complete multi-tenant, plan-limited, feature-gated
Projects CRUD in under 60 lines.

Everything else — auth, tenancy, RBAC, audit, plans, entitlements, usage,
billing — is framework infrastructure you already have running.

## Run it

```bash
# from the repo root, with the compose stack up
docker compose up -d postgres redis
export SYNAPSE_DATABASE_URL=postgresql+asyncpg://synapse:synapse@localhost:5433/synapse
uv run uvicorn examples.hello_saas.main:app --port 8020
```

Then, with a token + org header from the main API (port 8000):

```bash
curl -X POST http://localhost:8020/projects \
  -H "Authorization: Bearer $TOKEN" -H "X-Org-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"title": "First project"}'

curl http://localhost:8020/projects \
  -H "Authorization: Bearer $TOKEN" -H "X-Org-Id: $ORG_ID"
```

## What the framework gives this app for free

| Concern | Handled by |
|---|---|
| Authentication | `get_current_user` (JWT, rotation, Keycloak-ready) |
| Tenant resolution + isolation | `TenantDep` + `TenantRepository` |
| Permission checks | `require_permission("project:manage")` |
| Feature gating | `require_feature("api_access")` |
| Seat/project limits | `ensure_gauge_capacity` against the plan |
| Usage metering | `consume("projects")` per create |
| Audit trail | every mutation writes `project.*` audit rows |
| Problem+json errors | RFC 7807 with request ids |

## The whole domain app

```python
# examples/hello_saas/main.py — this is the entire application
```

Try the limits: on the **free** plan, the third project returns
`402 usage_limit_exceeded` with `{"metric": "projects", "limit": 2,
"upgrade_url": "/dashboard/billing"}`. Upgrade the org in the console
(/dashboard/billing) and try again.
