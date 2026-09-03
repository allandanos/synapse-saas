# Examples

Runnable samples — one per SDK, each against a live compose stack.

| Example | SDK | Shows |
|---|---|---|
| [`hello-saas/`](hello_saas/) | framework itself | a complete domain app: Projects CRUD, tenant-scoped by inheritance, plan-limited |
| [`multi-tenant/`](multi-tenant/) | Python | one user, two orgs, hard isolation; per-org usage/members/entitlements |
| [`subscription/`](subscription/) | TypeScript | freemium lifecycle: quota wall (402 + hints) → trial grant → plan upgrade |
| [`ai-saas/`](ai-saas/) | Go + Java | the SynapseDev.AI shape: metered inference calls, typed quota errors |

## Common setup

```bash
docker compose up -d          # the stack
# register a user + org via the console (localhost:3000), then:
export SYNAPSE_TOKEN=<access token>   # multi-tenant, subscription
export SYNAPSE_KEY=sk_…               # ai-saas (create in console → API keys)
```

## Running

```bash
cd examples/multi-tenant   # Python
uv run --project ../../sdk/python multi_tenant.py

cd examples/subscription   # TypeScript
pnpm install && pnpm start

cd examples/ai-saas/go     # Go
go run .

cd examples/ai-saas/java   # Java (install the SDK first: cd sdk/java && mvn install)
mvn -q compile exec:java
```
