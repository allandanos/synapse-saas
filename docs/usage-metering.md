# Usage Metering

Two metric kinds, three enforcement levels.

## Metrics

Defined in `config/plans.yaml` and synced to the `metrics` registry:

| Kind | Semantics | Example |
|---|---|---|
| `counter` | Consumed within a period; resets monthly | `api_requests`, `ai_tokens`, `storage_bytes` |
| `gauge` | Current capacity in use; no reset | `users` (seats), `projects` |

## Three APIs on UsageService

| Method | Blocks? | Use |
|---|---|---|
| `record` | Never | Metering/analytics — always succeeds |
| `check` | No (read-only) | Pre-flight UI: used / limit / remaining / soft flags |
| `consume` | Yes | Billable actions — 402 on breach |

```python
usage = UsageService(session)

await usage.record(org_id, "ai_tokens", quantity=12450)          # meter
await usage.check(org_id, "api_requests")                         # inspect
await usage.consume(org_id, "api_requests", quantity=1)           # enforce
```

## Atomic limit enforcement

`consume` is one SQL statement:

```sql
INSERT INTO usage_counters (organization_id, metric, period_start, quantity_total, ...)
VALUES (...)
ON CONFLICT (organization_id, metric, period_start)
DO UPDATE SET quantity_total = usage_counters.quantity_total + EXCLUDED.quantity_total
RETURNING quantity_total
```

The returned total is compared against the effective limit inside the same
transaction as the usage event. A breach raises `UsageLimitExceededError` →
HTTP **402** with `{metric, limit, used, upgrade_url}`, and the event +
counter roll back together. Concurrent consumers cannot overshoot undetected
(proven by a 10-way parallel test against a 3-slot limit).

## Gauges (seats)

Capacity metrics are enforced by count at the write site — `invite_member`
counts active + pending seats against the `users` limit inside the invite
transaction. Breach is the same 402 problem document.

## Soft limits

`soft_limit_ratio` on a metric (e.g. `0.8`) emits `usage.soft_limit_reached`
through the outbox exactly once per metric per period (guarded by
`usage_counters.soft_limit_notified_at`). Hard breaches emit
`usage.hard_limit_reached`. Consumers decide how to warn; the framework never
hard-blocks a *metered* call unless the app uses `consume`.

## Storage layout

- `usage_events` — append-only, **monthly range-partitioned** on `occurred_at`
  (UUIDv7 ids keep index locality); the worker pre-creates next month's
  partition and rollup rebuilds counters as drift correction
- `usage_counters` — one row per (org, metric, month); what limit checks read

## Idempotency

Events may carry an `idempotency_key`; a unique partial index makes retries
no-ops.
