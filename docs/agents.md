# Agents — governance, metering, and billing

> This framework **registers, gates, meters, and bills** agents. It does not
> execute them — that is the agent runtime's job. See
> [ADR 0007](adr/0007-agents-governance-not-execution.md) for the decision and
> its rationale.

## What the framework provides

| Concern | Mechanism |
|---|---|
| Which agents exist per org | `agents` table + `/v1/agents` CRUD (org-scoped, soft delete) |
| May this org run agents | `agents` feature key — Pro/Enterprise; 403 + upgrade hints otherwise |
| Who pays for AI | `ai_tokens` / `ai_requests` / `tool_calls` / `agent_executions` plan limits; token overage billed on invoices (₱0.20/1k) |
| What happened | `agent.registered` / `agent.updated` / `agent.disabled` webhook events via the outbox |
| Memory/knowledge storage | pgvector extension enabled; vector columns are yours to add |

The paywall is configuration: `config/plans.yaml` decides which plans carry
`agents`, exactly like every other feature key.

## The integration contract

```
user ──▶ synapse-saas console/API (auth, org, plan, entitlement, 403/402)
              │ issues org API key (scoped)
              ▼
         your product service ──SDK──▶ synapse-saas: gate + meter
         (any language)                  (agents.enabled; ai_tokens BEFORE spend)
              │ passes scoped key + tenant context forward
              ▼
         your agent runtime (e.g. synapse-agentic-runtime):
         runs the agent — MCP tools, A2A, memory, policies
              │ execution events (tokens used, tool calls)
              ▼
         product service meters actuals ──SDK──▶ synapse-saas usage API
```

### The metering loop, concretely

1. **Register the agent** (once): `POST /v1/agents` with the runtime's config
   (model, tool allowlist) stored opaque — the framework never interprets it.

2. **Pre-flight the spend** before invoking the runtime:

   ```http
   POST /v1/usage/consume
   { "events": [{ "metric": "ai_tokens", "quantity": 80000 }] }
   ```

   A 402 response (with `upgrade_url`) means the org's plan is exhausted —
   don't run. A 200 means the budget was reserved atomically.

3. **Execute** in the runtime. The service in the middle forwards the org's
   scoped key; the runtime's own policy layer gates tools inside the run.

4. **Meter actuals** after the run (estimates rarely equal reality):

   ```http
   POST /v1/usage/events
   { "events": [
     { "metric": "ai_tokens", "quantity": 76234 },
     { "metric": "tool_calls", "quantity": 12 },
     { "metric": "agent_executions", "quantity": 1 }
   ] }
   ```

5. **Period-end billing is automatic**: the invoice engine drafts overage
   lines from the entitlement resolver — the same source runtime enforcement
   uses. An addon grant of `limit:ai_tokens` shapes the bill exactly like it
   shapes the 402s.

## Console

`/dashboard/agents` — register, list, disable/enable. Non-entitled orgs see
the upgrade wall (sourced from the 403 problem document's `available_in` +
`upgrade_url`). Usage meters (`/dashboard/usage`) render every catalog metric,
including the AI four.

## Deferred to integration time (known, none architectural)

- **Auth vocabulary**: this framework uses `Authorization: Bearer sk_…`;
   runtimes expecting `X-API-Key` get a small adapter on one side.
- **Tenant context**: the calling service forwards org context; a convention
  worth pinning before it sprawls.
- **Tool-permission mapping**: runtime policy strings ↔ `resource:action`
  permission keys — a mapping table, a design afternoon.
- **Actuals reconciliation**: if you bill on real token counts, someone must
  turn runtime execution events into `usage/events` calls — an adapter job
  the outbox/webhook machinery already supports.
