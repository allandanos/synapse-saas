# Plans & Entitlements

Pricing is configuration. Application code asks the framework about features
and limits — never about plan names.

## The chain

```
Plan ──► Features ──► Entitlements ──► Permissions
```

`if plan == "pro"` is banned. `entitlements.has("advanced_reports")` is the API.

## Catalog (config/plans.yaml)

```yaml
features:
  - {key: advanced_reports, name: Advanced reports, category: reporting}

metrics:
  - {key: api_requests, kind: counter}

plans:
  - key: starter
    price_cents: 49900        # ₱499.00 — integer minor units
    trial_days: 14
    features: [basic_dashboard, api_access, reports]
    limits: {users: 10, api_requests: 100000}
```

Validation fails fast at startup: unknown features/metrics, duplicate keys,
`price: custom` xor `price_cents`, public plans need concrete prices. `make
plans-sync` (or app startup) upserts the catalog to the DB — additions and
edits apply; removals archive; **existing subscriptions' `plan_snapshot`s are
never rewritten** (grandfathering).

## Entitlement resolution

Effective features/limits for an org are resolved from:

1. **Plan features** — active while the subscription is `trialing`, `active`,
   or `past_due` (grace; disable with `SYNAPSE_GRACE_ON_PAST_DUE=false`)
2. **Grants** (`entitlements` table) — time-boxed, source-tagged rows that work
   independently of any plan

Grants resolve by source priority — a higher-priority grant wins, and a winning
`enabled: false` grant **removes** the feature (kill switch):

```
plan=0 < addon=10 < beta=20 < promo=30 < grandfather=40 < override=50 < enterprise=60
```

That single mechanism implements trials, add-ons, promotions, grandfathering,
beta access, enterprise overrides, and seat-cap add-ons — without application
changes.

### Limits as grants

A grant with feature key `limit:<metric>` overrides that metric's cap:

```json
POST /v1/entitlements/grants
{"feature_key": "limit:api_requests", "source": "addon", "limit_value": 250000}
```

## Using it

Backend gate:

```python
@router.get("/reports/advanced")
async def advanced_reports(_gate=Depends(require_feature("advanced_reports"))):
    ...
```

Breach payload is a 403 problem document with `feature`, `current_plan`,
`available_in`, `upgrade_url` — enough for the console to render an upgrade
dialog without another round trip.

Frontend gate:

```tsx
<FeatureGate feature="advanced_reports">
  <AdvancedReports />
</FeatureGate>
```

## Caching

Effective entitlements cache in Redis (version-counter invalidation, bumped on
every subscription/grant mutation) with a TTL-dict fallback when Redis is
absent. Hard limits are always re-checked at consume time against the DB
counter — never against cache alone.
