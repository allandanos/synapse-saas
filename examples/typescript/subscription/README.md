# subscription — freemium lifecycle with typed limits (TypeScript SDK)

The full monetization loop in ~50 lines: free plan → hit the seat quota (402
with upgrade hints) → trial grant unlocks the feature without a plan change →
plan upgrade raises the cap.

## Run

```bash
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_TOKEN=<access token for an org owner>

cd examples/subscription
pnpm install && pnpm tsx subscription.ts   # or: npx tsx subscription.ts
```

## What it shows

- `SynapseLimitError` carries `metric` + `limit` + `upgrade_url` — enough to
  render an upgrade prompt without another API call
- `entitlements.grant(..., durationDays)` — a time-boxed promo/trial that
  bypasses plan checks entirely
- `subscription.change()` — the cap moves; no downtime, no migration
