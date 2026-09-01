# ADR-0003: Gate on entitlements, never plan names

Date: 2026-08-31
Status: Accepted

## Context

Most starter SaaS templates gate with `if plan == "pro"`. That couples every
feature to the pricing table and makes trials, add-ons, promos, grandfathering,
and enterprise overrides into application changes.

## Decision

Plan features are resolved together with independent grants (the `entitlements`
table) into an immutable `EffectiveEntitlements` set:

- pure resolver (`entitlements/resolver.py`): DB rows in, features + limits out
- plan features apply while the subscription is trialing/active/past_due (grace configurable)
- grants win by source priority; `enabled: false` at a winning priority removes
  the feature (kill switch)
- `limit:<metric>` grants override per-metric caps — an add-on is just a grant
- `Depends(require_feature("x"))` / `<FeatureGate feature="x">` are the only
  gates; the 403 body carries `available_in` + `upgrade_url` so clients can
  render upgrade prompts without extra calls

## Consequences

+ Trials, add-ons, promos, beta flags, grandfathering, enterprise overrides:
  one mechanism, zero application changes
+ The resolver is pure → the entire pricing matrix is unit-tested without a DB
+ Limits live in the same resolution, so seat/API caps follow the same rules
− Two sources of truth (plan + grants) — the resolver is deliberately small and
  exhaustively tested to keep the merge obvious
