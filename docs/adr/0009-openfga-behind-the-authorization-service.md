# ADR 0009: OpenFGA behind the authorization service

## Status

Accepted (2026-09-28)

## Context

The original brief named OpenFGA for fine-grained authorization; the code had
a comment and Postgres RBAC. RBAC answers "may this member do X in this org"
well and is what every route asks. What it cannot answer is *resource-level*
sharing ("may this user edit **this** project, which someone shared with
them") without every domain app growing its own ACL tables.

## Decision

- **RBAC stays the source of truth** for what a role means. `permissions.py`
  is the catalog; `permission_keys_for()` (which feeds `UserContext`, API-key
  bounding and audit) stays RBAC whichever backend is active.
- **The OpenFGA model is generated from the catalog**
  (`authorization/fga_model.py`): `type organization` has one relation per
  system role and one computed `can_<resource>_<action>` per permission that
  unions the roles holding it; every `can_*` also accepts direct `[user]`
  tuples so custom roles are expressible. `type project` is the resource-level
  template (`viewer`/`editor` inherit from the org's permission or are
  granted per object). `render_dsl()` shows the same model as `.fga`; a test
  pins the two forms to the catalog.
- **`SYNAPSE_AUTHZ_BACKEND=openfga` switches the check**, not the data model:
  `AuthorizationService.user_can()` asks OpenFGA
  (`user:<id>` `can_…` `organization:<id>`), cached 30 s and invalidated with
  the permission cache. Failure mode is explicit: `closed` (deny — the
  production default) or `rbac` (fall back). API-key principals never consult
  OpenFGA — their authority is the key's scopes ∩ the creator's RBAC.
- **Tuples are synced from RBAC, asynchronously and exactly-once-ish**: every
  membership/role change appends an internal outbox event
  (`authz.tuples_changed`); the worker recomputes the member's desired tuples
  from the database and writes/deletes the difference. The outbox's retry and
  dead-letter machinery (ADR 0005) carries the sync; no request waits on
  OpenFGA writes.
- **`user_can_on(user, permission, object_type, object_id)`** is the
  resource-level API; the RBAC backend answers it at org level.
- `synapse-cli authz fga write-model | sync --all | check` bootstraps and
  audits a store.

## Consequences

- Nothing changes for deployments that keep `rbac`; the model, client and
  sync code are inert.
- With `openfga`, a store outage denies (closed) or degrades (rbac) —
  never silently allows.
- Domain apps get sharing by writing `project:<id>#viewer@user:<id>` tuples
  and asking `user_can_on`; no ACL tables.
- The CI job `integration-fga` proves the generated model's parity with RBAC
  against a real OpenFGA for every system role × permission.
