# REST contract changelog

`openapi-v1.json` is the frozen surface the console, the four SDKs, and the
language ports code against. Every change to it is listed here with intent.

## Unreleased

### Contract v1 freeze (P6 WS-K)

No path changes. Behaviour pinned by the new black-box suite
(`tests/conformance`, runnable in-process or against any base URL) and the
four SDKs, which now cover every non-exempt operation
(`scripts/sdk_coverage.py --check`).

- **Every error is a problem document.** Request-parsing failures used to be
  FastAPI's bare `{"detail": [...]}`; they are now `422` `validation_failed`
  with `type/title/status/detail/instance/request_id` and the parser's list in
  `errors[]`. Clients that read `detail` as a string keep working.
- Extensions can no longer shadow the RFC 7807 members (`status` in a problem
  body is always the HTTP status).
- `POST /v1/feature-flags` with an existing key answers **409** `conflict`
  (was a mislabelled 404).
- `POST /v1/files/{id}/presign` on a backend without presigned URLs answers
  **409** `presign_unsupported` (was 400 `storage_error`), the same type as
  `presign-upload`.
- Org suspension applies to JWT members too: **403** `organization_suspended`
  on every tenant route (was enforced for API keys only).
- `PATCH /v1/roles/{id}` echoes the permission set it just stored.
- `contracts/events.json` (public + internal event catalog) and
  `contracts/problems.json` (problem-type registry) are generated and checked in
  CI beside the OpenAPI document.

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

### SSO login (P5 WS-I, ADR 0010)

- **Added** `GET /v1/auth/oidc/start` and `GET /v1/auth/oidc/callback` —
  authorization-code flow with PKCE against Keycloak; the callback sets the
  refresh cookie and redirects to `{web_origin}/auth/callback`.
- **Changed** `POST /v1/auth/login` answers **401** with `sso_url` and
  `identity_provider` for SSO-only accounts (no local password).
- `/v1/meta` already reported `identity_provider`; the console uses it to show
  the SSO button.
- New settings: `SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT`, `SYNAPSE_OIDC_REDIRECT_URI`.

### Infrastructure, pagination, presigned uploads (P4 WS-F)

- **Added** `POST /v1/files/presign-upload` and `POST /v1/files/{id}/complete`
  (S3-compatible backends; local disk answers 409 `presign_unsupported`;
  mismatched uploads answer 409 `upload_incomplete`). `FileRead` gains `status`.
- **Changed** every list route accepts `?limit=` (1–100) and `?offset=` and
  sets `X-Total-Count` (exposed through CORS); bodies stay plain arrays.
  `GET /v1/files` no longer hard-caps at 200 rows. `GET /v1/webhooks/deliveries`
  replaces its ad-hoc `limit` with the same pair.
- CLI: `synapse-cli jobs run-once [--all | NAME…]` runs worker jobs on demand
  (what the Cloud Run worker job executes).

### Reliability and observability (P3 WS-D/WS-E, ADR 0005 amendment)

- **Changed** `GET /readyz` answers **503** (same body) when the database or a
  configured Redis fails its check; 200 only when everything answers.
- **Changed** problem documents' `request_id` is the server's request id
  (echoed in `X-Request-Id`), whether or not the client sent one.
- **Changed** webhook payload for `member.invited` is `{email, org_name,
  membership_id}` — the invite token no longer leaves the platform. Endpoints
  now only receive the event types in their `events` list (empty = all).
- Usage results for `usage.soft_limit_reached` payloads gain `organization_id`.
- New settings: `SYNAPSE_NOTIFIER`, `SYNAPSE_SMTP_TLS`, `SYNAPSE_SMTP_USERNAME`,
  `SYNAPSE_SMTP_PASSWORD`.

### Billing integrity (P2 WS-B, ADR 0004 amendment)

- **Changed** `POST /v1/subscription/change`: goes through the billing
  provider. Hosted providers answer **409 `checkout_required`** unless the
  subscription was purchased through them; local providers keep the period on
  paid→paid switches and queue a prorated correction for the period invoice.
- **Changed** `POST /v1/usage/consume`: more than one event is now **422**
  (`batch_url` points at the batch route) instead of silently dropping the rest.
- **Added** `POST /v1/usage/consume-batch` — all-or-nothing batch.
- **Added** `POST /v1/usage/gauge` — `{metric, value}` or `{metric, delta}` for
  gauge metrics (`users`, `projects`, `storage_bytes`). `/usage/events` and
  `/usage/consume` reject gauge metrics with 422.
- **Changed** usage results carry `deduplicated: bool`; an `idempotency_key`
  now really dedupes (per organization, 90-day retention).
- **Changed** overage invoice lines reconcile: `quantity` is the number of
  priced blocks, `unit_amount_cents` the block price, `amount == quantity × unit`
  (previously quantity was raw units and the line did not reconcile).
  `properties` carries `units_over`, `included`, `overage_unit`.
- **Changed** invoice drafts may carry `credit` / `custom` lines from prorated
  plan changes; a net credit never yields a negative invoice (carried forward).
- **Changed** webhook ingest responses gain `events_rejected`; a new
  `unprocessable` status marks payloads that could not be translated.
- Paddle webhooks: real `Paddle-Signature` format (`ts=…;h1=…` over `ts:body`).

### Baseline

- Captured from the Python reference implementation at P0 of the
  production-readiness plan. 71 operations across 13 routers.
