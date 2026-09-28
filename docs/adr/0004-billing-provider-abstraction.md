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

## Amendment (2026-09-28, P2 / WS-B)

- **Plan changes go through the provider.** `POST /subscription/change` calls
  `BillingService.change_plan`: a `recurring_hosted` provider is told (and must
  already hold the subscription — otherwise 409 `checkout_required`); local
  providers keep the period on paid→paid switches and queue an arrears
  proration for the period invoice. The previous route bypassed the provider
  entirely, so Stripe kept billing the old price.
- **Renewals are capability-driven and in arrears.** `advance_recurring_billing`
  covers every provider without `recurring_hosted` (not only Manual), claims
  rows with `SKIP LOCKED`, and issues the ended period's invoice through the
  invoicing engine instead of an inline `Invoice(...)`.
- **`client_confirm` capability.** Only Manual carries it; checkout
  confirmation is refused (409) for providers that verify payment themselves.
- **Webhook apply failures are no longer swallowed.** Business rejections are
  recorded on the ledger row (200); infrastructure failures roll the ledger
  back (500) so the provider's retry re-processes.
