# REST contract changelog

`openapi-v1.json` is the frozen surface the console, the four SDKs, and the
language ports code against. Every change to it is listed here with intent.

## Unreleased

Nothing yet.

## 0.4.1

`info.version` is `0.4.1`. No schema change; two behaviour changes on
existing operations, both tightening, plus a console dependency patch.

### Invite acceptance is bound to the invited address

- `POST /v1/auth/accept-invite` now answers 403 `permission_denied` when the
  signed-in caller's email is not the invite's `invited_email` (compared
  case-insensitively, whitespace-trimmed). Before, any signed-in user holding
  the emailed token could join. The console's `/register?invite=` and
  `/login?invite=` pages already render the problem's `detail`. **Ports:**
  mirror the check; covered by
  `tests/integration/test_email_flow.py::TestInviteAcceptance` here and by
  `tests/conformance/test_tenancy.py` once a port exposes invite tokens.

### `GET /v1/auth/me` with an API key is 403

- An `sk_` bearer resolved to a synthetic, unpersisted user and the response
  failed to serialise (500). It is now 403 `permission_denied`, matching
  PATCH; keys use the organization-scoped routes. **Ports:** conformance
  `tests/conformance/test_auth.py::test_get_me_with_an_api_key_is_403_problem`.

### Console image

- Next.js 16.3.3 → 16.4.3 and React 19.2.8 → 19.3.1: closes the advisories
  reported by `pnpm audit --prod` for the published `synapse-saas-web` image
  (two critical remote-code-execution issues in image handling, SSRF in the
  image optimizer, a server-actions denial of service, cache poisoning).
  Not a contract change; listed because the image is part of the release.

## 0.4.0

`info.version` is `0.4.0`. Additive: one new field on an existing schema;
every 0.3.1 client keeps working.

### Deployment tour steps

- **New field** `tour` (object, always present) on `BrandingRead`
  (`GET /v1/branding`): `TourConfig {enabled: boolean, hide: BuiltinStepId[],
  steps: TourStep[]}`; `TourStep {id, title, content, anchor, side, after,
  roles, permissions, icon, link}` with `link: TourStepLink {label, href} |
  null` and unset optionals as `null`. The id, anchor, side and icon sets are
  `enum`s in the schema; meaning and rules in
  [`docs/branding.md#product-tour`](../docs/branding.md#product-tour). The
  default (no `tour:` in `branding.yaml`) is
  `{"enabled": true, "hide": [], "steps": []}`. Intent: implementing apps
  that run the published images unmodified add their own onboarding steps to
  the console's welcome tour, hide built-in ones, or switch it off, from the
  branding kit instead of a fork.
- **Rollout:** API, worker and migrate images older than this release reject
  the `tour` key in `branding.yaml` at startup (`extra="forbid"`): upgrade the
  images first, then add the section.
- **SDKs:** none (the branding routes are exempt from SDK coverage).
- **Ports:** the Java and Node ports add the field returning the static
  default in M9; until then they fail
  `tests/conformance/test_branding.py::test_branding_document`.

## 0.3.1

`info.version` is `0.3.1`. Additive: one new field
on an existing schema plus a change to a system role's permissions; every 0.3.0
client keeps working.

### Permission-aware console navigation

- **New field** `permission_keys` (array of string, default `[]`) on
  `OrgSummary` (`GET`/`PATCH /v1/auth/me`, `orgs[]`). It is the caller's
  effective RBAC set in that org, sorted: the denormalised
  `memberships.permission_keys` that `require_permission` enforces, custom
  roles included. Platform admins pass every check regardless; the field
  carries their real membership set (nothing synthetic), so clients OR in
  `is_platform_admin`. Intent: the console hides nav items and gates pages
  and controls on it instead of rendering 403s.
- **Role change:** the system `member` role gains `member:read` (now
  `org:read`, `member:read`, `project:read`), so a plain member can read the
  member list. `GET /v1/roles` shares that gate, so members can also read the
  role catalog. Migration `0019_member_read` grants it and recomputes the
  stored set of every membership holding the system `member` role (a member
  who also holds a custom role keeps the union); the downgrade revokes and
  recomputes. No new operations or problem types.
- **OpenFGA:** the generated model's `can_member_read` gains `or member`. A
  running store keeps its old model id: operators on
  `SYNAPSE_AUTHZ_BACKEND=openfga` run `synapse-cli authz fga write-model`,
  point `SYNAPSE_OPENFGA_MODEL_ID` at the new id and restart.
- **SDKs:** no method changes; each `me` method's doc names
  `orgs[].permission_keys` (the response is untyped in all four).
- **Ports:** the Java and Node ports add the field, the role change and a
  mirror of migration 0019 in M9; until then they fail
  `tests/conformance/test_auth.py`'s permission-keys check.

## 0.3.0

`info.version` is `0.3.0`. Additive: one new field and one new method on an
existing path; every 0.2.1 client keeps working. First tags published to Docker
Hub after 0.2.0 (0.2.1 was tagged but its images were never pushed).

### User preferences

- **New field** `preferences` (object, default `{}`) on `UserWithOrgs`
  (`GET /v1/auth/me`). It is not on `UserRead`, so register, login and
  reset-password responses are unchanged.
- **New path method** `PATCH /v1/auth/me` with `MeUpdate {preferences?}`
  → `UserWithOrgs` (the GET shape). Intent: persist the console's product-tour
  completion (`{"tours": {"console-welcome": {"status", "version", "at"}}}`)
  server-side, and give forks a general per-user UI store.
- **Merge semantics:** the patch's top-level keys are merged into the stored
  object; a listed key is replaced wholesale (no deep merge, no "null deletes":
  reset a namespace with `{"tours": {}}`). An empty body or omitted
  `preferences` is a no-op 200.
- **Limits:** top-level keys match `^[a-z][a-z0-9_-]{0,63}$`; nested keys are
  free-form. Per request ≤ 32 keys, ≤ 16 KiB compact UTF-8 JSON, nesting ≤ 8
  levels; stored ≤ 64 keys and ≤ 32 KiB after the merge. Values JSON or JSONB
  cannot hold are refused at validation (422), never at the database: NaN and
  Infinity (Python's parser accepts them), NUL characters in keys or strings,
  and nesting past the cap however deep. Concurrent PATCHes by one user are
  serialised on the row, so neither merge overwrites the other.
- **Problems** (no new types): 401 without a bearer; 403 `permission_denied`
  for API-key (`sk_`) bearers, which have no user to write to; 422
  `validation_failed` for a bad key or any limit.
- **SDKs:** `update_me` (Python), `updateMe` (TypeScript, Java) and `UpdateMe`
  (Go) sit beside each SDK's `me` method and take a patch object.
- **Ports:** the Java and Node ports implement it in their next milestone with
  invite preview; until then they are not conformant on
  `tests/conformance/test_auth.py`'s preferences checks.

## 0.2.1

`info.version` is `0.2.1`. Additive: one new public path; every 0.2.0 client keeps working.

### Invite preview

- **New path** (public, no auth, no tenant): `GET /v1/auth/invite?token=<token>`
  → `InvitePreview {organization: {id, slug, name}, invited_email, role_keys}`.
  Intent: the console's join page (`/register?invite=` and `/login?invite=`)
  names the organization and prefills the invited email before the invitee
  registers or signs in. The token is not consumed; acceptance stays
  `POST /v1/auth/accept-invite` (single use).
- **Problems:** an unknown or already-used token is a 404 `invite_not_found`;
  a missing or too-short `token` (under 10 characters) is a 422
  `validation_failed`. The path is IP rate-limited with the other auth routes
  (429 `rate_limited`).
- **SDKs:** `preview_invite` (Python), `previewInvite` (TypeScript, Java) and
  `PreviewInvite` (Go) sit beside each SDK's accept-invite method.
- **Ports:** the Java and Node ports implement the path in their next milestone;
  until then they are not conformant on `tests/conformance/test_auth.py`'s
  invite-preview checks.

## 0.2.0 (tag pending)

First tagged release; it carries every entry below down to the baseline.
`info.version` is `0.2.0`. The `0.1.0` Docker images were a manual snapshot
of `b581b33` (contract as of "Findings from the ports' milestone 7") and do not
serve the branding paths.

### Distribution (P3)

No path changes. Production now refuses a `SYNAPSE_SECRET_KEY` shorter than 32
characters (blank included), alongside the dev-default check. Images are
published by `release.yml` on `v*` tags; `deploy/compose/` runs them.

### White-label branding (P1)

- **New paths** (public, no auth, no tenant): `GET /v1/branding` →
  `BrandingRead {name, tagline, assets, colors, links, landing, powered_by}`
  with origin-relative asset URLs, and `GET /v1/branding/assets/{name}`
  (SVG/PNG/ICO/CSS bytes; only assets `branding.yaml` names; anything else is
  a 404 `not_found` problem). Ports implement both to stay conformant
  (`tests/conformance/test_branding.py`); the SDKs exempt them as console
  presentation surface.
- `info.title` is now `"<brand name> API"` (`"Synapse API"` for the packaged
  kit, was `"Synapse SaaS Framework"`) and `info.description` the brand
  tagline when set. The contract is exported against the packaged kit.
- `GET /v1/meta` gains `product` (the brand name); `framework` stays
  `"synapse-saas"`.
- New problem title `branding_invalid` (startup/CLI only — never served: the
  API refuses to start on an invalid kit).
- Emails carry the brand as sender display name, product name and footer;
  invoice PDFs print the branded issuer block and no longer say "Generated by
  the Synapse SaaS Framework".

### Findings from the ports' milestone 7 (P7)

No path changes. Behaviour fixes the ports surfaced:

- OpenFGA: tuples now converge eagerly after the mutating transaction commits
  (in addition to the outbox event), and organization creation queues the
  owner's tuples — a new org's owner used to be denied in `openfga` mode until
  a manual `authz fga sync`. A missing delete is tolerated in OpenFGA 1.x's
  wording ("cannot delete a tuple which does not exist"), not only "not found".
- `SYNAPSE_KEYCLOAK_ALLOW_PASSWORD_GRANT=true` now does what it says: the
  password form proxies unknown or SSO-only accounts to Keycloak (ROPC) and
  links/creates them; it was a dead setting.
- The console's SSO journey works on Keycloak 26 (the version the nightly job
  pins): the password field is addressed by role, and a brand-new SSO user is
  expected to land on onboarding.
- Dead `member` cache namespace removed from tenant resolution.

### Findings from the ports' milestone 5 (P7)

- `file.uploaded`, `file.deleted`, `webhook.endpoint_created` and
  `webhook.endpoint_deleted` were in the public event catalog but nothing
  emitted them, and the matching actions left no audit rows. They now fire
  (outbox + audit, in the same transaction; endpoint payloads never carry the
  secret). `webhook.endpoint_updated` is **removed** from the catalog: no
  route updates an endpoint. The conformance suite asserts the audit rows.
- `POST /v1/feature-flags/{key}/overrides` requires exactly one scope:
  both `organization_id` and `user_id` is 422 (it was silently stored as a
  user override).
- `GET /v1/webhooks/endpoints` is ordered (`created_at` desc, id) so pages
  never repeat or skip a row.

### Findings from the ports' milestone 4 (P7)

- The `invoice.email` handler resolves its recipient through the same chain
  as every other billing mail (billing customer → `settings.billing_email`
  → org owner). Framework-drafted invoices carry no billing customer, so on
  the manual flow the mail was silently dropped unless the org had set a
  billing email.
- Xendit amounts (`"499.99"` major units) are converted to minor units with
  decimal arithmetic; the float path turned 0.29 into 28 (ADR 0006).
- `POST /v1/billing/invoices/{id}/finalize` on an already-open invoice is a
  no-op (same number, same `issued_at`, no second `invoice.created` /
  `invoice.email`); it used to re-number the invoice.

### Findings from the ports' milestone 3 (P7)

- `GET /v1/usage/summary?period=` and `POST /v1/billing/invoices/draft`
  `{period}` validate the month (`^\d{4}-(0[1-9]|1[0-2])$`); `2026-13` answers
  422 `validation_failed` instead of a 500 from the date parser.
- `contracts/problems.json` entries now carry `classes` (every exception
  class that renders the title) instead of a single `class`, and the exporter
  refuses two classes with one title but different statuses. Statuses and
  titles are unchanged; `plan_not_found` for example lists both
  `PlanNotFoundError` and `PlanNotPublicError`.

### Findings from the Node port's milestone 2 (P7)

Implementing the contract a second time exposed places where the document, the
reference and the conformance suite disagreed. The reference wins; the others
were corrected.

- `POST /v1/auth/switch-org` is **200** with `{access_token, token_type,
  expires_in}` (the document said 204/no body; the server always answered 200).
- Unknown routes and wrong methods are problem documents (`not_found`,
  `method_not_allowed`) instead of Starlette's bare `{"detail": ...}`.
- `POST /v1/orgs/current/members/invite` answers **409** `conflict` for an email
  already invited or a member (was a 500 from the unique constraint), and the
  response now carries the assigned `role_keys` (was `[]`).
- `POST /v1/roles` answers **409** `conflict` for a duplicate key (was a 500);
  the conformance test for an unknown permission now asserts the reference's
  **403** `permission_denied` (it previously passed only because its fixture
  name was too short).
- Tenant resolution ignores IP-literal hosts (`127.0.0.1` no longer resolves
  the slug `127`); the JWT `org` claim is used instead.
- The invite email event carries the real organization name.
- `contracts/schema-v1.sql` keeps `SET check_function_bodies = false`.

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
