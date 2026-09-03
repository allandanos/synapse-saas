# hello-saas (TypeScript) — a complete domain app on the framework

Projects CRUD — multi-tenant, permission-checked, feature-gated, plan-limited,
metered, and audited. This is the entire application; everything else is
framework infrastructure.

## Run

```bash
# stack up, then create a user + org via the console (localhost:3000)
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_TOKEN=<access token>
export SYNAPSE_ORG=<org uuid>

cd examples/typescript/hello-saas
pnpm install && pnpm start
```

## What the framework gives this app for free

| Concern | Handled by |
|---|---|
| Authentication | access-token credentials in the SDK |
| Tenant resolution + isolation | org-scoped client (`orgId`) |
| Feature gating | `api_access` entitlement on upload-flavored routes |
| Plan limits | 402 `SynapseLimitError` with upgrade hints when the project cap trips |
| Usage metering | per-project gauge meters on every create |
| Problem+json errors | typed SDK errors with request ids |

## Note

The Python hello-saas variant defines a real `Project(TenantMixin)` ORM model
and router inside the framework process — it shows server-side extension.
This TypeScript variant drives the same behavior from **client code** through
the running API: list, create until the plan's project cap trips, delete.
