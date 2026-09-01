# Multi-tenancy

Every organization's data is isolated. The application never writes
`WHERE organization_id = ?` — the framework does, or the query doesn't run.

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

## RLS (optional)

`SYNAPSE_TENANT_ISOLATION=app_and_rls` additionally creates Postgres row-level
security policies keyed off the transaction-local `app.current_tenant` setting.
Application-level filtering remains the primary boundary; RLS catches what a
code slip would otherwise leak. Off by default for clone-and-run; recommended
in production.
