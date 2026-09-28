# REST contract changelog

`openapi-v1.json` is the frozen surface the console, the four SDKs, and the
language ports code against. Every change to it is listed here with intent.

## Unreleased

### Operator vs tenant split (P1 WS-A, ADR 0008) — **breaking**

Grants and money movements are platform-operator actions. Tenants could
previously grant themselves entitlements (`entitlement:manage` sat on the
owner/admin roles) and mark their own invoices paid.

- **Removed** `POST /v1/entitlements/grants` (tenant route).
- **Removed** `POST /v1/billing/invoices/{invoice_id}/pay` and `/void` (tenant routes).
- **Added** `GET /v1/admin/orgs/{org_id}/entitlements`,
  `POST /v1/admin/orgs/{org_id}/entitlements/grants`,
  `DELETE /v1/admin/orgs/{org_id}/entitlements/grants/{grant_id}` — platform-admin
  bearer, explicit org in the path, no `X-Org-Id`.
- **Added** `POST /v1/billing/admin/invoices/{invoice_id}/pay` and `/void` —
  platform-admin bearer. Tenants keep draft / finalize / read / pdf.
- `entitlement:manage` stays in the permission catalog but no tenant system
  role carries it.
- SDKs: `entitlements.grant(...)` now takes the organization id first and needs
  a platform-admin token. Console admin page grants by org id.

### API keys are bounded by their creator (P1 WS-A)

Not a path change, but a semantic one clients may observe:

- `POST /v1/api-keys` with an empty `scopes` now snapshots the creator's
  permissions instead of meaning "everything"; an explicit list must be a
  subset of the creator's permissions or the call fails 403 with
  `exceeds_creator: [...]`.
- Key-authenticated requests are denied 403 with `reason` in
  `unbounded_key | creator_inactive | creator_lacks_permission` when the
  creating user can no longer exercise the permission.
- Migration `0014` backfills existing empty-scope keys from the creator's
  current membership.

### Checkout confirm is capability-gated (P1 WS-A)

- `POST /v1/billing/checkout/confirm` answers **409 `checkout_confirm_not_allowed`**
  unless the configured provider declares `client_confirm` (only the manual
  provider does). Hosted-checkout providers activate via their webhook only.

### Baseline

- Captured from the Python reference implementation at P0 of the
  production-readiness plan. 71 operations across 13 routers.
