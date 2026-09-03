# multi-tenant (TypeScript) — two orgs, one user, hard isolation

Same scenario as the Python variant, driven from TypeScript: a user belongs
to two organizations; every client call is scoped to exactly one.

## Run

```bash
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_TOKEN=<access token owning 2+ orgs>

cd examples/typescript/multi-tenant
pnpm install && pnpm start
```

## What it shows

- Org-scoped clients (`orgId`) vs the un-scoped one — different views
- Usage consumed in org A never moves org B's counters
- Member invites count against each org's own seat quota
