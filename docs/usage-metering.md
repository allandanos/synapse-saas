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

Events may carry an `idempotency_key` (unique per organization). The key is
reserved in `usage_idempotency_keys` *before* the event is written, so a retry
— even a concurrent one — waits for the first request to commit and then gets
the stored result back with `deduplicated: true` instead of counting again.
(`usage_events` is range-partitioned, so a unique index there could never
dedupe across the partition key; that was the old, broken design.) A `consume`
that breaches rolls the reservation back with everything else, so the retry
re-attempts and 402s again. Keys are purged after 90 days.

## Batches

`POST /usage/consume` takes exactly one event (two or more is a 422 — it used
to silently drop the rest). `POST /usage/consume-batch` is all-or-nothing: the
first breach 402s and nothing in the batch is counted. `POST /usage/events`
records many events and never blocks.

## Gauges

`kind: gauge` metrics (`users`, `projects`, `storage_bytes`) are **levels**, not
flows. They live in a fixed bucket that never resets with the month and are
written through `POST /usage/gauge` with `{metric, value}` (set) or
`{metric, delta}` (move, never below zero). `/usage/events` and
`/usage/consume` reject gauge metrics with a 422. The framework keeps `users`
in step with memberships (invites hold a seat) and `storage_bytes` in step with
uploads and deletes; domain apps set their own (`projects`).

A positive `delta` is capacity-checked in the same transaction (402 with
upgrade hints when it would exceed the cap), so "add a project" is one call:
`adjust_gauge(org, "projects", 1)`; deleting one is `adjust_gauge(…, -1)`.
