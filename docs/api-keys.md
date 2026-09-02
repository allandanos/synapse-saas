# API Keys

Programmatic access to an organization's resources — the developer-facing
credential alongside user JWTs.

## Model

- Plaintext `sk_<43 urlsafe chars>` — generated once, **SHA-256 hashed at rest**;
  the plaintext is returned exactly once at creation and never again
- `prefix` (first 8 chars, e.g. `sk_ab12cd`) stored for display
- Optional `expires_in_days`; optional `scopes`; revocable
- Every key belongs to one organization — tenant isolation applies identically

## Using a key

```bash
curl https://api.example.com/v1/usage/summary \
  -H "Authorization: Bearer sk_…"
```

No `X-Org-Id` needed: a key authenticates **as its organization**. The key's
org is pinned; a supplied `X-Org-Id` is ignored (tested).

## Scopes

Scopes are permission keys (`usage:read`, `project:manage`, …). An **empty
scope list means full access** — everything the creating user could exercise.
A key can never exceed its creator's authority, and scope enforcement reuses
the RBAC gate:

```python
await require_permission("project:manage", user, session, tenant)
# → for key principals: checked against key scopes instead of RBAC
```

Denied requests are `403 permission_denied` with `"auth": "api_key"`.

## Metering

Every key-authenticated request meters one `api_requests` unit against the
organization's plan quota (soft — never blocks; `consume` is the explicit
blocking path). `last_used_at` updates on each use.

## Management API

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/api-keys` | prefix, status, last_used — never the plaintext |
| POST | `/v1/api-keys` | `{name, scopes?, expires_in_days?}` → plaintext once |
| DELETE | `/v1/api-keys/{id}` | revoke; key stops working immediately |

Permission: `apikey:manage` (owner/admin/developer roles).

## Failure modes — all opaque 401

Unknown key, revoked key, expired key, and suspended org all return the same
`401 unauthorized`. The caller learns nothing about which condition failed.

## Events

`api_key.created`, `api_key.revoked` — emitted through the outbox (webhook
deliveries included) and written to the audit log.
