# Multi-tenancy

Every organization's data is isolated, by three layers that fail
independently: `TenantRepository` scopes reads and writes of `TenantMixin`
models automatically; service code that builds its own queries filters on the
resolved tenant explicitly (there are ~30 such sites — grep
`organization_id ==`); and with `SYNAPSE_TENANT_ISOLATION=app_and_rls` the
database itself refuses rows outside the request's tenant (row-level
security, ADR 0002). The last layer is the one the integration suite runs as
a real non-owner role (`make test-rls`).

## Model

```
Platform
 ├── Organization A ── memberships ── users, roles, subscription, entitlements, usage…
 ├── Organization B ── …
 └── Organization C ── …
```

A user may belong to many organizations. Membership carries roles and a
denormalized `permission_keys` snapshot for cheap authorization checks.

## Tenant resolution

Per request, in order:

1. `X-Org-Id` header (UUID)
2. `X-Org-Slug` header
3. Subdomain (`acme.app.example.com`)
4. JWT `org` claim (set by `POST /v1/auth/switch-org`)

Then membership is verified. **Failure is always 404** with a body identical to
a nonexistent org — the API never leaks which organizations exist.

Operator suspension (`POST /v1/orgs/{id}/suspend`, ADR 0008) is checked *after*
membership, for every principal: members get **403** `organization_suspended`
(with `organization_id` and `organization_status`), API keys of that org fail
authentication, and a non-member still sees the same 404 as before. Platform
admins keep access so they can investigate.

## Tenant-scoped persistence

Inherit `TenantMixin` and use `TenantRepository`:

```python
from synapse_saas.core.db import Base, TenantMixin
from synapse_saas.core.repository import TenantRepository

class Project(TenantMixin, Base):
    __tablename__ = "projects"
    title: Mapped[str]

class ProjectRepo(TenantRepository[Project]):
    model = Project
```

- `repo.list()` — tenant-filtered automatically
- `repo.get(id)` — another tenant's row resolves to `None` (→ 404)
- `repo.add(obj)` — stamps the tenant; an object stamped with a different org
  raises `TenantViolationError`
- Worker jobs pass `tenant_id=` explicitly (contextvars don't cross tasks)

## Contextvars — the async rule

Tenant/user context is carried in `contextvars`. They are copied at task
creation and do **not** propagate into `asyncio.create_task` bodies set later,
nor into worker jobs. Any background work must carry `organization_id`
explicitly and re-establish context:

```python
from synapse_saas.core.context import TenantContext, TenantScope

async with TenantScope(TenantContext(organization_id=org_id, slug=slug)):
    await do_tenant_work()
```

This is pinned by `tests/unit/core/test_context.py`.

## RLS (defense-in-depth, role-bound)

`SYNAPSE_TENANT_ISOLATION=app_and_rls` makes Postgres enforce tenancy underneath
the application filter. Every organization-scoped table carries a
`tenant_isolation` policy (migration 0013) that admits a row when any of these
transaction-local settings match:

| GUC | Set by | Admits |
|---|---|---|
| `app.current_tenant` | tenant resolution, right after the org row is found and before the membership check | rows of that organization |
| `app.current_user` | authentication (JWT or API key) | a user's own `memberships` / `feature_flag_overrides` — the pre-tenant reads behind `/auth/me`, org listing, invite acceptance |
| `app.rls_platform = on` | `PlatformAdminDep` surfaces | every row |
| — | — | `organization_id IS NULL` rows on platform-scope tables (`roles`, `audit_logs`, `outbox_events`, `feature_flag_overrides`) |

Enforcement is bound to the **connection role**, not to `FORCE`:

- The API connects as a `LOGIN NOBYPASSRLS` role that owns nothing —
  `synapse-cli db provision-app-role` creates it and grants DML plus default
  privileges for future tables. Point `SYNAPSE_DATABASE_URL` at it.
- The worker, CLI, and migrations connect as the schema owner
  (`SYNAPSE_WORKER_DATABASE_URL`) and bypass policies (`NO FORCE`). Worker jobs
  always use the owner session factory; they are never subject to RLS.
- At startup the API queries its own role and refuses to run if the role and the
  flag disagree: a bypassing role with RLS on would be a false sense of security;
  a subject role with RLS off would see zero rows.

Two lookups legitimately happen before the tenant is known — accepting an invite
(by token hash; an invited membership has no `user_id`) and applying a billing
webhook (by provider ids). Each uses a narrow `SECURITY DEFINER` function that
returns only the organization id, after which the request binds the tenant and
continues under policy. Two credential tables are deliberately not policed:
`api_keys` and `refresh_tokens` are looked up by secret hash before any tenant
exists, and the hash is the authorization.

Off by default so clone-and-run works with the image's superuser. Recommended in
production. `make test-rls` runs the entire integration suite as the subject role;
`tests/integration/test_rls_enforcement.py` proves the policies from a clean
connection regardless of which role the main suite uses.
