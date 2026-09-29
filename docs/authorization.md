# Authorization

Two layers, one catalog.

| | Answers | Source of truth | Backend |
|---|---|---|---|
| **RBAC** | "may this member do `resource:action` in this org?" | `authorization/permissions.py` (system roles) + custom roles in Postgres | always on |
| **Fine-grained (OpenFGA)** | the same question, plus "may this user edit **this** project?" | the same catalog, projected into an OpenFGA model; tuples synced from RBAC | `SYNAPSE_AUTHZ_BACKEND=openfga` |

Every route goes through `require_permission("resource:action")`. Platform
admins pass; API keys authorize against their scopes ∩ their creator's RBAC
(never OpenFGA); members go through `AuthorizationService.user_can()`, which
is RBAC or OpenFGA depending on the backend. `UserContext.permission_keys`
(audit, key bounding) is always the RBAC set.

## RBAC

- 21 permissions (`org:read` … `agents:manage`); `entitlement:manage` is an
  operator permission no tenant role carries (ADR 0008)
- System roles: owner, admin, billing, developer, member — seeded, immutable
- Custom roles: `POST /v1/roles` with any permission subset; members hold any
  mix. `memberships.permission_keys` is the denormalized union, recomputed on
  every role change and cached 30 s (`perm` cache, invalidated after commit)

## OpenFGA (ADR 0009)

### Model

Generated from the catalog by `authorization/fga_model.py`, so it cannot
drift (a unit test pins every role × permission):

```
type organization
  relations
    define owner: [user]            # one relation per system role
    define admin: [user]
    …
    define can_org_delete: [user] or owner            # one per permission
    define can_billing_read: [user] or owner or admin or billing
    …
type project                        # the resource-level template
  relations
    define org: [organization]
    define viewer: [user] or editor or can_project_read from org
    define editor: [user] or can_project_manage from org
```

Every `can_*` accepts direct `[user]` tuples: custom roles are written as
direct grants, so the model needs no per-tenant relations.
`synapse-cli authz fga write-model --dsl` prints it.

### Bring-up

```bash
docker compose --profile extras up -d openfga          # dev: in-memory store
export SYNAPSE_OPENFGA_URL=http://localhost:8081
uv run synapse-cli authz fga write-model --create-store synapse
#   store_id=…  authorization_model_id=…
export SYNAPSE_OPENFGA_STORE_ID=… SYNAPSE_OPENFGA_MODEL_ID=…
uv run synapse-cli authz fga sync --all                # backfill tuples from RBAC
export SYNAPSE_AUTHZ_BACKEND=openfga
```

### Tuple sync

Tuples converge twice: eagerly right after the mutating transaction commits
(an after-commit action, best effort, so a member who just gained a role is
not denied for the dispatch interval plus the decision cache), and durably
through the internal `authz.tuples_changed` outbox event the worker consumes
(retries, dead-lettering). The worker's pass normally finds an empty diff.
Organization creation queues the owner's tuples like every other role change.


Every membership or role change (invite accepted, roles replaced, member
suspended/removed, custom role edited) appends the internal outbox event
`authz.tuples_changed`; the worker recomputes the member's desired tuples
from the database and writes/deletes the difference
(`authorization/sync.py`). Retries, backoff and dead-lettering come from the
outbox (ADR 0005); `synapse-cli authz fga sync --org <id>` repairs by hand.

Desired tuples for a member: one `organization:<org>#<role>@user:<id>` per
system role, plus a direct `can_<perm>` tuple for each permission that only
a custom role grants.

### Failure mode

| `SYNAPSE_OPENFGA_FAIL_MODE` | Store unreachable ⇒ |
|---|---|
| `closed` (default) | deny (403), `synapse_fga_checks_total{outcome="error"}` increments |
| `rbac` | fall back to the RBAC answer for org-level checks |

Decisions are cached 30 s per (user, object) and invalidated with the
permission cache.

### Resource-level checks

```python
await AuthorizationService(session).user_can_on(user.id, "project:manage", "project", project_id)
```

Domain apps write `project:<id>#org@organization:<org>` when creating a
project (inherits the org's permissions) and `project:<id>#viewer@user:<uid>`
to share it. With the RBAC backend, `user_can_on` answers only for
`object_type="organization"`.

### Verification

`tests/integration/test_openfga_parity.py` (CI job `integration-fga`, a real
OpenFGA) proves every system role × permission answers the same as RBAC and
runs a route end to end with `SYNAPSE_AUTHZ_BACKEND=openfga`.
