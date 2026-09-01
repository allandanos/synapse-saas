# ADR-0004: BillingProvider abstraction over raw httpx

Date: 2026-08-31
Status: Accepted

## Context

The framework must not be locked to one payment provider — including to none.
A Philippine SaaS needs Xendit/PayMongo; a global one needs Stripe; local dev
and enterprise contracts need no provider at all. Vendor SDKs (e.g.
`stripe-python`) are sync-first and would force adapters inside every provider.

## Decision

- `billing/protocol.py` defines the ABC; all four providers implement it over a
  shared `httpx.AsyncClient` — no vendor SDKs
- Webhook handling is split: `verify_webhook(raw)` (signatures over exact
  bytes) and `translate_webhook(verified)` (schema → `NormalizedBillingEvent`)
- Providers declare `supports: frozenset[BillingCapability]`; the worker's
  manual-billing scheduler covers providers without hosted recurring
- Ingest is idempotent via a unique `(provider, provider_event_id)` ledger
- Manual is the default provider so the stack runs with zero external accounts

## Consequences

+ Uniform providers; signature verification is unit-testable with respx and
  no network (valid/tampered/stale/wrong-secret per provider)
+ One webhook vocabulary — application code never parses provider payloads
+ Adding a provider touches `providers/` + registry only
− We hand-maintain endpoint/form-encoding details the Stripe SDK would own;
  acceptable while our Stripe surface (checkout, portal, subscriptions,
  invoices, webhooks, plan sync) is small
− Xendit/PayMongo recurring is thinner than Stripe's; capability flags keep
  that honest instead of pretending parity
