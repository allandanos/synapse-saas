# API Reference

Live OpenAPI docs: **`/docs`** (Swagger) and **`/redoc`** on a running API.

Conventions:

- Base path `/v1`; JSON bodies; **every** error is an RFC 7807 problem document
  (`application/json`): `type`, `title`, `status`, `detail`, `instance`,
  `request_id`, plus typed extensions (`metric`/`limit` on 402, `feature`/
  `available_in` on 403 gates, …). Request-parsing failures are
  `validation_failed` (422) with the per-field list in `errors[]`. The registry
  is `contracts/problems.json`.
- `X-Request-Id` is honored inbound and echoed outbound
- Org context via `X-Org-Id` (UUID) or `X-Org-Slug`; unauthorized cross-tenant
  access is 404 identical to a nonexistent org

## Pagination

Every list route accepts `?limit=` (1–100, default 50) and `?offset=`. The
body stays a plain JSON array; the total number of rows rides the
`X-Total-Count` response header (exposed through CORS).

## Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | 201 + tokens |
| POST | `/auth/login` | tokens; refresh also set as httpOnly cookie |
| POST | `/auth/refresh` | rotation; reuse outside grace revokes the session |
| POST | `/auth/accept-invite` | `{token}` from the invite email joins the caller's user to the org |
| GET | `/auth/oidc/start?return_to=` | SSO (Keycloak): 302 to the IdP with PKCE + nonce; state kept server-side 10 min ([identity](identity.md)) |
| GET | `/auth/oidc/callback?code&state` | SSO return: verifies the id_token, links/creates the user, sets the refresh cookie, 302 to the console's `/auth/callback` |
| POST | `/auth/logout` | 204 |
| GET | `/auth/me` | user + orgs + role keys |
| POST | `/auth/switch-org` | 200 `{access_token, token_type, expires_in}` scoped to the org (`org` claim resolves the tenant when no header is sent); rotated refresh token in the cookie |
| POST | `/auth/forgot-password` | 202, opaque response |
| POST | `/auth/reset-password` | tokens + new password |

## Organizations & members

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/orgs` | — |
| GET/PATCH | `/orgs/current` | `org:read` / `org:update` |
| GET | `/orgs/current/members` | `member:read` |
| POST | `/orgs/current/members/invite` | `member:invite` (seat limit enforced); 409 `conflict` when the email is already invited or a member |
| PATCH/DELETE | `/memberships/{id}` | `member:update` / `member:remove` |
| POST/DELETE | `/orgs/{id}/suspend` | platform admin; while suspended every member gets **403** `organization_suspended`, API keys 401 |

## Roles

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/roles` | `member:read` / `role:manage`; unknown permission → 403 `permission_denied` (`unknown[]`), duplicate key → 409 `conflict` |
| PATCH/DELETE | `/roles/{id}` | `role:manage` (system roles immutable) |
| GET | `/permissions` | catalog |

## Plans & subscription

| Method | Path | Notes |
|---|---|---|
| GET | `/plans` | public plans only |
| GET | `/subscription` | subscription + entitlements + usage in one call |
| POST | `/subscription/trial` | 409 if already trialing |
| POST | `/subscription/change` | through the billing provider: hosted providers need a purchased subscription (**409 `checkout_required`**), local providers prorate paid→paid changes |
| POST | `/subscription/cancel` | `{at_period_end: true\|false}` |
| POST | `/subscription/resume` | 404 if not scheduled to cancel |

## Billing

| Method | Path | Notes |
|---|---|---|
| POST | `/billing/checkout` | `{url}` (hosted) or manual instructions |
| POST | `/billing/checkout/confirm` | manual-provider activation |
| GET | `/billing/portal-url` | provider portal, null when unsupported |
| GET | `/billing/invoices` | org invoices |
| GET | `/billing/invoices/{id}` | invoice detail with lines (plan, overage, credit/custom) |
| GET | `/billing/invoices/{id}/pdf` | framework-rendered PDF (`Content-Disposition` carries the number) |
| POST | `/billing/invoices/draft` | `{period?: "YYYY-MM"}` — draft (or return) the period invoice: plan + catalog-priced overage + prorated adjustments (`billing:manage`) |
| POST | `/billing/invoices/{id}/finalize` | assign a number, lock amounts, queue the delivery email (`billing:manage`) |
| GET | `/billing/spend-summary` | this org's billed / paid / outstanding totals (`billing:read`) |
| GET | `/billing/spend-monthly` | this org's monthly spend series (`billing:read`) |
| GET | `/billing/admin/revenue-summary` | **platform admin** — revenue across orgs |
| GET | `/billing/admin/revenue-monthly` | **platform admin** — monthly revenue series |
| POST | `/billing/admin/invoices/{id}/pay` | **platform admin** — record an out-of-band payment (tenants cannot mark their own invoice paid) |
| POST | `/billing/admin/invoices/{id}/void` | **platform admin** — void an open invoice |
| POST | `/billing/webhooks/{provider}` | raw-body ingest; provider-verifiable |

## Entitlements & usage

| Method | Path | Notes |
|---|---|---|
| GET | `/entitlements` | effective features + limits |
| GET | `/admin/orgs/{org_id}/entitlements` | **platform admin** — effective entitlements for any org |
| POST | `/admin/orgs/{org_id}/entitlements/grants` | **platform admin** — sources: trial/addon/promo/beta/override/enterprise/grandfather. Tenants cannot grant themselves entitlements (ADR 0008) |
| DELETE | `/admin/orgs/{org_id}/entitlements/grants/{grant_id}` | **platform admin** — revoke a grant |
| POST | `/usage/events` | batch ≤100; metering never blocks; `idempotency_key` dedupes (`deduplicated: true` on replay) |
| POST | `/usage/consume` | exactly one event (422 otherwise); atomic; **402** with `{metric, limit, used, upgrade_url}` on breach |
| POST | `/usage/consume-batch` | all-or-nothing batch ≤100; first breach 402s and nothing is counted |
| POST | `/usage/gauge` | set (`value`) or move (`delta`) a gauge metric — seats, projects, bytes; a positive delta is capacity-checked (**402**) |
| GET | `/usage/check?metric=` | pre-flight |
| GET | `/usage/summary` | per-metric meters for the console |

## Files

| Method | Path | Notes |
|---|---|---|
| GET | `/files` | org listing (`file:read`) |
| POST | `/files` | multipart ≤10 MiB (`file:write` + `api_access`); meters `storage_bytes` |
| GET | `/files/{id}` | stream download |
| POST | `/files/presign-upload` | reserve quota + PUT URL for a direct upload (S3 backends; 409 on local disk) |
| POST | `/files/{id}/complete` | verify the uploaded object and mark it ready (409 `upload_incomplete` on mismatch) |
| POST | `/files/{id}/presign` | time-limited direct download URL (S3 backends; 409 `presign_unsupported` on local disk) |
| DELETE | `/files/{id}` | soft-delete + object delete + quota released |

## Feature flags

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/feature-flags` | platform admin; list / create (409 `conflict` on a duplicate key) |
| PATCH | `/feature-flags/{key}` | flip default / rollout |
| GET/POST | `/feature-flags/{key}/overrides` | org/user overrides |
| DELETE | `/feature-flags/overrides/{id}` | remove override |
| GET | `/feature-flags/check/{key}` | resolve for caller (org-scoped) |

See [Feature flags](feature-flags.md) — deployment toggles, distinct from entitlements.

## API keys

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/api-keys` | `apikey:manage`; POST returns the plaintext once |
| DELETE | `/api-keys/{id}` | revoke |

`sk_…` bearers authenticate as the key's org on any endpoint — see
[API keys](api-keys.md).

## Webhooks & audit

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/webhooks/endpoints` | `webhook:manage` (secret shown once) |
| DELETE | `/webhooks/endpoints/{id}` | `webhook:manage` |
| GET | `/webhooks/deliveries` | `webhook:manage` |
| POST | `/webhooks/deliveries/{id}/retry` | `webhook:manage` |
| GET | `/audit` | `audit:read`; filters `event_type`, `actor_user_id` |

## Agents

Registry and governance only (ADR 0007); execution lives in the sibling
agentic runtime. Every route is behind the `agents` feature (403 with
`available_in` on plans without it).

| Method | Path | Notes |
|---|---|---|
| GET | `/agents` | org registry (`agents:read`); paginated |
| POST | `/agents` | register `{slug, name, description?, config?}` (`agents:manage`) |
| GET | `/agents/{id}` | one agent (`agents:read`) |
| PATCH | `/agents/{id}` | update name/description/config (`agents:manage`) |
| DELETE | `/agents/{id}` | remove (`agents:manage`) |
| POST | `/agents/{id}/enable` | (`agents:manage`) |
| POST | `/agents/{id}/disable` | kill switch (`agents:manage`) |

## Branding

Public — no auth, no tenant. The console renders its name, logo, favicon,
colours and links from it; emails and invoice PDFs read the same kit
in-process. Configured per deployment by `branding.yaml`
(`SYNAPSE_BRANDING_FILE`; `synapse-cli branding init|validate`).

| Method | Path | Notes |
|---|---|---|
| GET | `/branding` | `{name, tagline, assets, colors, links, landing, powered_by}`; `assets.*` are origin-relative URLs (`/v1/branding/assets/<name>?v=<sha256[:8]>`) or null; `Cache-Control: public, max-age=60`. Email and invoice settings are never exposed |
| GET | `/branding/assets/{name}` | only the files `branding.yaml` names as `logo`, `logo_dark`, `favicon`, `custom_css`; anything else is a 404 `not_found` problem. `nosniff`, a day of caching (the `?v=` digest busts it); SVG adds `Content-Security-Policy: default-src 'none'` |

## Health

| Method | Path |
|---|---|
| GET | `/healthz`, `/readyz` (**503** when a dependency fails), `/v1/meta` |

## Status codes

| Code | Meaning |
|---|---|
| 402 | usage/seat limit exceeded (upgrade hints included) |
| 403 `feature_not_entitled` | plan gate (with `available_in`) |
| 403 `permission_denied` | RBAC |
| 404 | missing resource **or cross-tenant** (indistinguishable by design) |
