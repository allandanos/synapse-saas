# ADR-0006: Money as integers; raw-body webhook verification

Date: 2026-08-31
Status: Accepted

## Context

Two recurring SaaS correctness traps: floating-point money, and webhook
signatures broken by frameworks that pre-parse request bodies.

## Decisions

**Money** — integer minor units + ISO-4217 codes everywhere
(`price_cents BIGINT`, `currency CHAR(3)`). Providers that use major units
(Xendit sends `499.0`) convert exactly once at the provider boundary. Console
formatting (₱1,999.00) derives from minor units. Never floats.

**Webhook bodies** — the ingest route reads `await request.body()` exactly once
and hands the raw bytes to `verify_webhook`. Any middleware that buffers or
re-parses the body would invalidate every signature, so the pattern is
documented here and pinned by signature tests (tampered body, stale timestamp,
wrong secret, malformed header per provider).

Replay protection is the `(provider, provider_event_id)` unique ledger — not
the timestamp window (±5 min is a freshness bound, not an anti-replay one).

## Consequences

+ No rounding drift, ever; aggregates over `*_cents` are exact
+ Signatures verify over what the provider actually signed
+ Provider retries are safe; replays are 200 no-ops with zero re-application
