# API Reference

Live OpenAPI docs: **`/docs`** (Swagger) and **`/redoc`** on a running API.

Conventions:

- Base path `/v1`; JSON bodies; RFC 7807 `application/problem+json` errors
- `X-Request-Id` is honored inbound and echoed outbound
- Org context via `X-Org-Id` (UUID) or `X-Org-Slug`; unauthorized cross-tenant
  access is 404 identical to a nonexistent org

## Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | 201 + tokens |
| POST | `/auth/login` | tokens; refresh also set as httpOnly cookie |
| POST | `/auth/refresh` | rotation; reuse outside grace revokes the session |
| POST | `/auth/logout` | 204 |
| GET | `/auth/me` | user + orgs + role keys |
| POST | `/auth/switch-org` | re-scopes the session to one org |
| POST | `/auth/forgot-password` | 202, opaque response |
| POST | `/auth/reset-password` | tokens + new password |

## Organizations & members

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/orgs` | — |
| GET/PATCH | `/orgs/current` | `org:read` / `org:update` |
| GET | `/orgs/current/members` | `member:read` |
| POST | `/orgs/current/members/invite` | `member:invite` (seat limit enforced) |
| PATCH/DELETE | `/memberships/{id}` | `member:update` / `member:remove` |
| POST/DELETE | `/orgs/{id}/suspend` | platform admin |

## Roles

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/roles` | `member:read` / `role:manage` |
| PATCH/DELETE | `/roles/{id}` | `role:manage` (system roles immutable) |
| GET | `/permissions` | catalog |

## Plans & subscription

| Method | Path | Notes |
|---|---|---|
| GET | `/plans` | public plans only |
| GET | `/subscription` | subscription + entitlements + usage in one call |
| POST | `/subscription/trial` | 409 if already trialing |
| POST | `/subscription/change` | upgrades apply immediately |
| POST | `/subscription/cancel` | `{at_period_end: true\|false}` |
| POST | `/subscription/resume` | 404 if not scheduled to cancel |

## Billing

| Method | Path | Notes |
|---|---|---|
| POST | `/billing/checkout` | `{url}` (hosted) or manual instructions |
| POST | `/billing/checkout/confirm` | manual-provider activation |
| GET | `/billing/portal-url` | provider portal, null when unsupported |
| GET | `/billing/invoices` | org invoices |
| POST | `/billing/webhooks/{provider}` | raw-body ingest; provider-verifiable |

## Entitlements & usage

| Method | Path | Notes |
|---|---|---|
| GET | `/entitlements` | effective features + limits |
| POST | `/entitlements/grants` | `entitlement:manage`; sources: trial/addon/promo/beta/override/enterprise/grandfather |
| POST | `/usage/events` | batch ≤100; metering never blocks |
| POST | `/usage/consume` | atomic; **402** with `{metric, limit, used, upgrade_url}` on breach |
| GET | `/usage/check?metric=` | pre-flight |
| GET | `/usage/summary` | per-metric meters for the console |

## Files

| Method | Path | Notes |
|---|---|---|
| GET | `/files` | org listing (`file:read`) |
| POST | `/files` | multipart ≤10 MiB (`file:write` + `api_access`); meters `storage_bytes` |
| GET | `/files/{id}` | stream download |
| POST | `/files/{id}/presign` | time-limited direct URL (S3 backends) |
| DELETE | `/files/{id}` | soft-delete + object delete |

## Feature flags

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/feature-flags` | platform admin; list / create |
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

## Health

| Method | Path |
|---|---|
| GET | `/healthz`, `/readyz`, `/v1/meta` |

## Status codes

| Code | Meaning |
|---|---|
| 402 | usage/seat limit exceeded (upgrade hints included) |
| 403 `feature_not_entitled` | plan gate (with `available_in`) |
| 403 `permission_denied` | RBAC |
| 404 | missing resource **or cross-tenant** (indistinguishable by design) |
