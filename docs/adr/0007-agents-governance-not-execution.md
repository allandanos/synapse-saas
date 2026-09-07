# ADR 0007: Agents — governance and commerce, not execution

## Status

Accepted (2026-09-07)

## Context

The original design brief put two peers side by side:

```
SYNAPSE SaaS Runtime          SYNAPSE Agentic Runtime
  Tenancy                       Agents
  Identity                      MCP
  Billing                       A2A
  Entitlements                  Tools
  Usage                         Memory
  Authorization                 Workflows
```

Phase 4 ("Agentic") in this repo was therefore always going to touch agents.
A sibling project, `synapse-agentic-runtime`, already implements the
right-hand column: planner/executor loops, MCP tool plumbing, A2A protocol,
multi-provider model calls, policies with hard tool pre-checks, memory
backends. It is substantially built and battle-shaped for exactly that job.

Building a second executor here would mean owning two agent runtimes under
one umbrella — "integration" would stop being wiring and become a
which-one-wins decision with a deprecation cost. That is the one genuinely
painful path, and it is avoidable by scoping now.

## Decision

**This framework governs and bills agents; it does not execute them.**

Phase 4 in `synapse-saas` delivers exactly the left-hand-column services
applied to agents:

1. **Registry** — an org-scoped `agents` table: which agents exist per
   tenant, their opaque config (model, prompt refs, tool allowlists —
   owned by whichever runtime executes them), enabled/disabled status.
   It is the CRM for agents, not an agent runner.
2. **Entitlement gating** — `agents` as a feature key, so "AI Agents" is
   a paid plan line resolved through the same `require_feature` machinery
   as every other gate (403 + upgrade hints).
3. **AI usage metering as a first-class flow** — `ai_tokens`,
   `ai_requests`, `tool_calls`, `agent_executions` metrics wired into
   plan limits and (for `ai_tokens`) overage pricing that rides the
   invoice engine: grandfathered plan snapshots, entitlement-included
   amounts, and overage math identical to seats today.
4. **Webhook events** — `agent.registered`, `agent.updated`,
   `agent.disabled` through the existing transactional outbox.
5. **pgvector enablement** — the one-line extension migration, so agent
   knowledge/memory storage never needs a coordinated enable later.

## The integration contract

The canonical wiring with `synapse-agentic-runtime` (or any runtime):

```
user ──▶ synapse-saas console/API (auth, org, plan, entitlement, 403/402)
              │ issues org API key (scoped)
              ▼
         your product service ──SDK──▶ synapse-saas: gate + meter
         (any language)                  (agents.enabled; ai_tokens BEFORE spend)
              │ passes scoped key + tenant context forward
              ▼
         synapse-agentic-runtime: runs the agent (MCP tools, A2A, memory)
              │ execution events (tokens used, tool calls)
              ▼
         product service meters actuals ──SDK──▶ synapse-saas usage API
```

The SaaS framework never knows how to run an agent; the runtime never
knows whose agent it is or who pays for the tokens. The service in the
middle (built on the domain-service extension pattern, `docs/extending.md`)
owns forwarding tenant context.

## Consequences

- No planner/executor, MCP client, A2A, model-provider abstraction, or
  memory backend will be added to this repo. A future proposal to do so
  must overturn this ADR explicitly.
- Known frictions deferred to integration time (all adapters, none
  architectural): auth vocabulary (`Bearer sk_…` vs `X-API-Key`),
  tenant-context forwarding conventions, tool-permission string mapping
  (runtime policy strings ↔ `resource:action`), metering actuals vs
  estimates reconciliation.
- The narrow scope is fully self-contained and demonstrable end-to-end
  without any external runtime (a test-double executor suffices).
