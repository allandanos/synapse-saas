# multi-tenant — two orgs, one user, hard isolation (Python SDK)

Demonstrates the framework's core promise in ~40 lines: a user belongs to two
organizations, and every request is scoped to exactly one — the other org's
data is invisible (404, identical to nonexistent).

## Run

```bash
# 1. Stack up (compose), then create a user + two orgs via the console or API
# 2. Export credentials:
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_TOKEN=<access_token from login>

cd examples/multi-tenant
uv run --project ../../sdk/python multi_tenant.py
```

## What it shows

- `client.orgs.list()` — both orgs for the user
- `SynapseClient(..., org_id=ORG_A)` vs `org_id=ORG_B` — same user, scoped views
- Inviting a member counts against org A's seat quota only
- Usage metered per org: consuming in A never moves B's counters
