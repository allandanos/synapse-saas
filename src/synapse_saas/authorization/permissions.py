"""Canonical permission catalog.

Every permission key is `resource:action`. This module is the single source of
truth — seeded into the `permissions` table and referenced by `require_permission`.
"""

from __future__ import annotations

from typing import NamedTuple


class PermissionDef(NamedTuple):
    key: str
    resource: str
    action: str
    description: str


PERMISSIONS: tuple[PermissionDef, ...] = (
    # Organization
    PermissionDef("org:read", "org", "read", "View organization details"),
    PermissionDef("org:update", "org", "update", "Update organization profile and settings"),
    PermissionDef("org:delete", "org", "delete", "Delete the organization"),
    # Members
    PermissionDef("member:read", "member", "read", "List members and their roles"),
    PermissionDef("member:invite", "member", "invite", "Invite new members"),
    PermissionDef("member:update", "member", "update", "Change member roles and status"),
    PermissionDef("member:remove", "member", "remove", "Remove members from the organization"),
    # Roles
    PermissionDef("role:manage", "role", "manage", "Create, update, and delete custom roles"),
    # Billing & subscription
    PermissionDef("billing:read", "billing", "read", "View subscription, plans, and invoices"),
    PermissionDef("billing:manage", "billing", "manage", "Change plans, start trials, manage payment"),
    # Usage & audit
    PermissionDef("usage:read", "usage", "read", "View usage meters and limits"),
    PermissionDef("audit:read", "audit", "read", "View the organization audit log"),
    # Webhooks
    PermissionDef("webhook:manage", "webhook", "manage", "Manage webhook endpoints and view deliveries"),
    # Entitlements
    PermissionDef("entitlement:manage", "entitlement", "manage", "Grant or revoke feature entitlements"),
    PermissionDef("apikey:manage", "apikey", "manage", "Create, list, and revoke API keys"),
    # Files
    PermissionDef("file:read", "file", "read", "List and download organization files"),
    PermissionDef("file:write", "file", "write", "Upload and delete organization files"),
    # Project-scoped example (the pattern domain apps extend)
    PermissionDef("project:read", "project", "read", "View projects"),
    PermissionDef("project:manage", "project", "manage", "Create, update, and delete projects"),
)

PERMISSION_KEYS: frozenset[str] = frozenset(p.key for p in PERMISSIONS)


# ── System roles ───────────────────────────────────────────────────────────────

SYSTEM_ROLE_OWNER = "owner"
SYSTEM_ROLE_ADMIN = "admin"
SYSTEM_ROLE_BILLING = "billing"
SYSTEM_ROLE_DEVELOPER = "developer"
SYSTEM_ROLE_MEMBER = "member"

_OWNER = {p.key for p in PERMISSIONS}
_ADMIN = _OWNER - {"org:delete"}
_BILLING = {"org:read", "billing:read", "billing:manage", "usage:read"}
_DEVELOPER = {
    "org:read",
    "member:read",
    "project:read",
    "project:manage",
    "webhook:manage",
    "usage:read",
    "apikey:manage",
}
_MEMBER = {"org:read", "project:read"}

SYSTEM_ROLES: dict[str, dict[str, object]] = {
    SYSTEM_ROLE_OWNER: {
        "name": "Owner",
        "description": "Full control, including deleting the organization",
        "permissions": sorted(_OWNER),
    },
    SYSTEM_ROLE_ADMIN: {
        "name": "Admin",
        "description": "Manage everything except deleting the organization",
        "permissions": sorted(_ADMIN),
    },
    SYSTEM_ROLE_BILLING: {
        "name": "Billing",
        "description": "Manage subscription, plans, and invoices",
        "permissions": sorted(_BILLING),
    },
    SYSTEM_ROLE_DEVELOPER: {
        "name": "Developer",
        "description": "Build on the platform: projects, webhooks, usage visibility",
        "permissions": sorted(_DEVELOPER),
    },
    SYSTEM_ROLE_MEMBER: {
        "name": "Member",
        "description": "Day-to-day access to org resources",
        "permissions": sorted(_MEMBER),
    },
}
