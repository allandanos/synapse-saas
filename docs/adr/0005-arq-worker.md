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
