"""Permission catalog sanity — the RBAC contract."""

from __future__ import annotations

from synapse_saas.authorization.permissions import (
    PERMISSION_KEYS,
    PERMISSIONS,
    SYSTEM_ROLES,
)


class TestCatalog:
    def test_all_keys_unique(self) -> None:
        keys = [p.key for p in PERMISSIONS]
        assert len(keys) == len(set(keys))

    def test_keys_are_resource_action(self) -> None:
        for perm in PERMISSIONS:
            assert perm.key == f"{perm.resource}:{perm.action}", perm.key

    def test_permission_keys_matches(self) -> None:
        assert {p.key for p in PERMISSIONS} == PERMISSION_KEYS

    def test_owner_has_every_tenant_permission(self) -> None:
        # entitlement:manage is an operator permission — no tenant role holds it (ADR 0008)
        owner = set(SYSTEM_ROLES["owner"]["permissions"])  # type: ignore[arg-type]
        assert owner == PERMISSION_KEYS - {"entitlement:manage"}

    def test_admin_lacks_only_org_delete(self) -> None:
        admin = set(SYSTEM_ROLES["admin"]["permissions"])  # type: ignore[arg-type]
        owner = set(SYSTEM_ROLES["owner"]["permissions"])  # type: ignore[arg-type]
        assert admin == owner - {"org:delete"}

    def test_no_tenant_role_can_grant_entitlements(self) -> None:
        for key, role in SYSTEM_ROLES.items():
            assert "entitlement:manage" not in role["permissions"], key  # type: ignore[operator]

    def test_member_is_least_privileged(self) -> None:
        member = set(SYSTEM_ROLES["member"]["permissions"])  # type: ignore[arg-type]
        assert member < set(SYSTEM_ROLES["developer"]["permissions"])  # type: ignore[arg-type]

    def test_every_role_permission_exists(self) -> None:
        for role in SYSTEM_ROLES.values():
            unknown = set(role["permissions"]) - PERMISSION_KEYS  # type: ignore[arg-type]
            assert not unknown, f"{unknown} do not exist"
