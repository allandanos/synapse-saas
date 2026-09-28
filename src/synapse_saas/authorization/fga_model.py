"""The OpenFGA authorization model, generated from the permission catalog (ADR 0009).

RBAC stays the source of truth for *what* a role means (`permissions.py`);
this module projects it into an OpenFGA model so the two can never disagree:

- `type organization` carries one relation per system role (`owner`, `admin`,
  …) and one computed relation per permission (`can_org_delete`, …) that
  unions the roles holding it. Every `can_*` relation also accepts direct
  `[user]` tuples so custom roles (any permission set) can be expressed.
- `type project` is the resource-level template domain apps copy: a `viewer`
  / `editor` relation that inherits from the org's permission or is granted
  per object (sharing).

`build_model()` returns the JSON the OpenFGA API accepts; `render_dsl()`
renders the same thing as the human-readable `.fga` DSL for docs and review.
"""

from __future__ import annotations

from typing import Any

from synapse_saas.authorization.permissions import PERMISSIONS, SYSTEM_ROLES

SCHEMA_VERSION = "1.1"
ROLE_ORDER = ("owner", "admin", "billing", "developer", "member")


def relation_for(permission: str) -> str:
    """`org:delete` → `can_org_delete`."""
    return "can_" + permission.replace(":", "_")


def roles_holding(permission: str) -> list[str]:
    return [role for role in ROLE_ORDER if permission in SYSTEM_ROLES[role]["permissions"]]  # type: ignore[operator]


# ── JSON (API) form ───────────────────────────────────────────────────────────


def _direct(*types: str) -> dict[str, Any]:
    return {"this": {}}


def _union(*children: dict[str, Any]) -> dict[str, Any]:
    if len(children) == 1:
        return children[0]
    return {"union": {"child": list(children)}}


def _computed(relation: str) -> dict[str, Any]:
    return {"computedUserset": {"relation": relation}}


def _tuple_to_userset(tupleset: str, relation: str) -> dict[str, Any]:
    return {"tupleToUserset": {"tupleset": {"relation": tupleset}, "computedUserset": {"relation": relation}}}


def _user_type() -> dict[str, Any]:
    return {"type": "user", "relations": {}, "metadata": None}


def _organization_type() -> dict[str, Any]:
    relations: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for role in ROLE_ORDER:
        relations[role] = _direct("user")
        metadata[role] = {"directly_related_user_types": [{"type": "user"}]}
    for perm in PERMISSIONS:
        rel = relation_for(perm.key)
        holders = roles_holding(perm.key)
        relations[rel] = _union(_direct("user"), *(_computed(role) for role in holders))
        metadata[rel] = {"directly_related_user_types": [{"type": "user"}]}
    return {"type": "organization", "relations": relations, "metadata": {"relations": metadata}}


def _project_type() -> dict[str, Any]:
    relations = {
        "org": _direct("organization"),
        "viewer": _union(
            _direct("user"), _computed("editor"), _tuple_to_userset("org", relation_for("project:read"))
        ),
        "editor": _union(_direct("user"), _tuple_to_userset("org", relation_for("project:manage"))),
    }
    metadata = {
        "org": {"directly_related_user_types": [{"type": "organization"}]},
        "viewer": {"directly_related_user_types": [{"type": "user"}]},
        "editor": {"directly_related_user_types": [{"type": "user"}]},
    }
    return {"type": "project", "relations": relations, "metadata": {"relations": metadata}}


def build_model() -> dict[str, Any]:
    """The authorization model in the OpenFGA API's JSON form."""
    return {
        "schema_version": SCHEMA_VERSION,
        "type_definitions": [_user_type(), _organization_type(), _project_type()],
    }


# ── DSL form (for humans) ─────────────────────────────────────────────────────


def render_dsl() -> str:
    lines = ["model", f"  schema {SCHEMA_VERSION}", "", "type user", "", "type organization", "  relations"]
    lines.extend(f"    define {role}: [user]" for role in ROLE_ORDER)
    for perm in PERMISSIONS:
        rel = relation_for(perm.key)
        holders = " or ".join(roles_holding(perm.key))
        rhs = "[user]" + (f" or {holders}" if holders else "")
        lines.append(f"    define {rel}: {rhs}")
    lines += [
        "",
        "type project",
        "  relations",
        "    define org: [organization]",
        f"    define viewer: [user] or editor or {relation_for('project:read')} from org",
        f"    define editor: [user] or {relation_for('project:manage')} from org",
        "",
    ]
    return "\n".join(lines)


__all__ = ["ROLE_ORDER", "SCHEMA_VERSION", "build_model", "relation_for", "render_dsl", "roles_holding"]
