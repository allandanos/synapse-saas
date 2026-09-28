# ADR 0008: Operator vs tenant surfaces

## Status

Accepted (2026-09-28)

## Context

The audit that opened the production-readiness plan found two ways a tenant
could act on its own commercial standing:

- `entitlement:manage` sat on the `owner` and `admin` system roles, and
  `POST /v1/entitlements/grants` was an org-scoped route. Any owner could grant
  itself `sso`, or raise its own caps with a `limit:<metric>` grant.
- `POST /v1/billing/invoices/{id}/pay` and `/void` were tenant routes gated by
  `billing:manage`. Any billing-role member could mark the org's own invoice
  paid without money moving.

Both routes existed because the framework needed *some* way to grant a trial
or record a bank transfer, and the org-scoped router was the only surface with
tests. Nothing distinguished "the platform team acting on a tenant" from "the
tenant acting on itself".

A third, related hole sat in API keys: an empty scope list meant "everything",
and scopes were never checked against the creating user's permissions, so a
developer-role member could mint a key that held `org:delete`.

## Decision

**Some actions are the operator's, never the tenant's.** They live on a
separate surface, authenticated by a platform-admin user, with the target
organization explicit in the path and no `X-Org-Id` header:

| Action | Route | Dependency |
|---|---|---|
| Inspect effective entitlements | `GET /v1/admin/orgs/{org_id}/entitlements` | `PlatformAdminDep` |
| Grant a feature or limit override | `POST /v1/admin/orgs/{org_id}/entitlements/grants` | `PlatformAdminDep` |
| Revoke a grant | `DELETE /v1/admin/orgs/{org_id}/entitlements/grants/{grant_id}` | `PlatformAdminDep` |
| Record an out-of-band payment | `POST /v1/billing/admin/invoices/{id}/pay` | `PlatformAdminDep` |
| Void an open invoice | `POST /v1/billing/admin/invoices/{id}/void` | `PlatformAdminDep` |

The tenant routes are removed, not deprecated. `entitlement:manage` stays in
the permission catalog (custom operator roles may carry it) but no tenant
system role does; the catalog test pins that.

Non-admins get **404**, not 403, from the operator surface. The surface is
invisible to tenants, consistent with how `require_platform_admin` already
answered.

Tenants keep everything that is theirs: draft and finalize invoices, read and
download them, change plans, start checkout. Whether a plan change *reaches*
the payment provider is a separate defect (WS-B).

**API keys can never exceed their creator.** At creation, an explicit scope
list must be a subset of the creator's effective permissions (403 with
`exceeds_creator`), and an empty list is *snapshotted* to the creator's
permissions, not left as "everything". At request time the key's scopes are
intersected with the creator's *current* permissions, so demoting or removing
the creator shrinks or disables their keys immediately. A key minted by a key
is rooted at the human who created the parent. Migration `0014` backfills
existing empty-scope keys. Audit rows written under key auth are attributed to
that human with `actor_type="api_key"` and the key id in the diff; the key's
sentinel `user_id` matches no `users` row and is never written to a FK.

## Consequences

- The console's admin page grants by organization id. The e2e journeys and
  SDK examples log in as the dev-seeded platform operator
  (`synapse-cli seed --dev`) for the grant and payment steps.
- SDK `entitlements.grant(...)` takes the organization id first and requires
  a platform-admin token. The manual-provider "bank transfer" flow is now an
  operator action by construction, which is what it always was in practice.
- Integration tests grant through `grant_as_platform` /
  `pay_as_platform` / `void_as_platform` helpers in `conftest.py`, so the
  suite exercises the same surface operators use.
- `contracts/openapi-v1.json` records the route moves; `contracts/CHANGELOG.md`
  marks them breaking.
- Custom tenant roles can still be created with `entitlement:manage` by a
  tenant with `role:manage`, but the permission gates nothing on the tenant
  surface any more, so that is harmless. A later change may hide operator
  permissions from the tenant role editor.
