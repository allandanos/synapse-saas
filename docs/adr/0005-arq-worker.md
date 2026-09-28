# ADR-0005: arq for background jobs

Date: 2026-08-31
Status: Accepted

## Context

The outbox needs a dispatcher, deliveries need retry loops, usage needs
rollups, entitlements need expiry, manual billing needs period rolls, and
partitions need pre-creation. Candidates: Celery (ecosystem, but sync-first)
or arq (async-native, Redis-only).

## Decision

arq. Jobs live in `worker/jobs.py`; the cron schedule in `WorkerSettings`.
Every job re-establishes `TenantContext` from explicit payload — contextvars
do not cross task/process boundaries by design.

Crons: dispatch_outbox 5s · deliver_webhooks 15s · rollup_usage hourly ·
expire_entitlements hourly · advance_manual_billing hourly ·
ensure_partitions daily · purge_expired daily.

## Consequences

+ Async-native: reuses the framework's async SQLAlchemy/Redis/httpx verbatim
+ Uses the Redis we already run; built-in cron; ~2 files
+ `FOR UPDATE SKIP LOCKED` makes multi-worker dispatch safe
− No Celery ecosystem (flower, routing); irrelevant at this scope. If the
  framework later needs heavy task topology, jobs are plain functions and can
  be re-registered elsewhere

## Amendment (2026-09-28, P3 / WS-D)

- **Outbox audience.** `outbox_events.audience` is `public` (fans out to
  tenant webhook endpoints, filtered by each endpoint's `events`) or
  `internal` (in-process handlers only). Invite tokens, reset links and
  invoice mail are internal; the public `member.invited` carries no token.
- **Retry and dead-letter.** Each event dispatches in its own savepoint;
  failures record `attempts`/`last_error`/`next_attempt_at` with backoff and
  the row is dead-lettered (`dead_at`) after 8 attempts. Emails run after the
  dispatch commit.
- **Delivery claims** use `FOR UPDATE SKIP LOCKED`; the outbound HTTP client
  is one shared instance (`core/http.py`) closed on shutdown.
- **Recurring billing** is capability-driven (`advance_recurring_billing`,
  see ADR 0004) and bills the ended period through the invoicing engine.
- **Partitions** are created three months ahead with a DEFAULT partition as
  the safety net; **retention** keeps exhausted deliveries 90 days, purges
  published outbox rows after 7, and honours `SYNAPSE_AUDIT_RETENTION_DAYS`.
- **Cache invalidation** is deferred to after commit (`core/cache.defer_bump`);
  jobs use `commit_and_flush_bumps` or an explicit post-commit invalidation.
