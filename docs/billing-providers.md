# Billing Providers

One protocol, four implementations. The framework is not locked to a payment
provider — including to none at all.

## Provider matrix

| Provider | Checkout | Portal | Hosted recurring | Plan sync | Webhook auth | Status |
|---|---|---|---|---|---|---|
| **Manual** (default) | internal page | — | worker scheduler | — | shared token | production-ready for dev/enterprise contracts |
| **Stripe** | hosted | ✅ | ✅ | ✅ | HMAC `Stripe-Signature` | full integration |
| **Xendit** (PH) | invoice URL | — | invoice-cycle | — | `X-Callback-Token` | interface-complete, less battle-tested |
| **PayMongo** (PH) | checkout session | — | local scheduling | — | HMAC `Paymongo-Signature` | interface-complete, less battle-tested |

Select with `SYNAPSE_BILLING_PROVIDER`. The default is `manual` so
`docker compose up` gives you the entire freemium loop with zero external
accounts.

## The protocol

`billing/protocol.py` defines `BillingProvider` over raw httpx (no vendor SDKs
— uniform providers, testable signatures). Webhook handling is deliberately
split:

- `verify_webhook(raw)` — signature/timestamp check over the exact bytes
- `translate_webhook(verified)` — parsed JSON → `NormalizedBillingEvent`s

Verification is transport security; translation is schema mapping. The router
reads `await request.body()` **once** before anything parses it — middleware
that touches the body would break every signature (guarded by tests).

## Normalized events

Every provider maps onto one vocabulary: `subscription.activated|updated|canceled|past_due`,
`invoice.created|paid|failed`, `checkout.completed`, `payment.failed`. Ingest:

1. Verify (400 on bad signature/token)
2. Insert `provider_webhook_events` ON CONFLICT DO NOTHING — **duplicate ⇒ 200 no-op**
3. Apply each normalized event idempotently (upserts keyed on provider ids +
   subscription state machine)

Out-of-order delivery and retries are safe by construction.

## Capability honesty

Providers declare `supports: frozenset[BillingCapability]`. Where
`RECURRING_HOSTED` is absent (Manual, Xendit, PayMongo today), the worker's
`advance_recurring_billing` job renews: it invoices the period that just ended
**in arrears** through the invoicing engine (plan line + catalog-priced
overage + prorated corrections, numbered, emailed), then rolls the period. Rows
are claimed with `FOR UPDATE SKIP LOCKED`, each renewal is its own savepoint.
Hosted providers (Stripe) renew on their side and report through webhooks.
Services check capabilities, never provider names.

Plan changes follow the same split (`BillingService.change_plan`): with a
hosted provider the subscription must have been purchased through it
(`provider_subscription_id`), otherwise **409 `checkout_required`**; the
provider is told and owns proration. With a local provider a paid→paid switch
keeps the billing period and queues an arrears correction (the elapsed
fraction at the price difference) for that period's invoice; a free→paid
upgrade starts a fresh cycle today.

`client_confirm` marks providers whose activation the tenant may confirm
without a provider callback (only Manual). `POST /billing/checkout/confirm`
answers 409 for every other provider — hosted checkouts activate via webhook.

## Plans ↔ provider objects

`plans.provider_refs` jsonb maps plan → provider product/price ids. Push the
catalog with:

```bash
synapse-cli plans sync --provider stripe           # dry-run diff
synapse-cli plans sync --provider stripe --apply   # create products/prices, record refs
```

## Configuration

```bash
SYNAPSE_BILLING_PROVIDER=stripe
SYNAPSE_STRIPE_SECRET_KEY=sk_...
SYNAPSE_STRIPE_WEBHOOK_SECRET=whsec_...
```

Point provider webhooks at `POST /v1/billing/webhooks/{provider}`.
