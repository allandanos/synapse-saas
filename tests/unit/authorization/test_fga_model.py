"""The generated OpenFGA model mirrors the permission catalog exactly (ADR 0009)."""

from __future__ import annotations

from synapse_saas.authorization.fga_model import (
    ROLE_ORDER,
    build_model,
    relation_for,
    render_dsl,
    roles_holding,
)
from synapse_saas.authorization.permissions import PERMISSIONS, SYSTEM_ROLES


def _org_type() -> dict:
    return next(t for t in build_model()["type_definitions"] if t["type"] == "organization")


class TestModelMirrorsCatalog:
    def test_every_permission_has_a_relation(self) -> None:
        relations = _org_type()["relations"]
        for perm in PERMISSIONS:
            assert relation_for(perm.key) in relations, perm.key

    def test_every_system_role_is_a_relation(self) -> None:
        relations = _org_type()["relations"]
        assert set(ROLE_ORDER) == set(SYSTEM_ROLES) and all(r in relations for r in ROLE_ORDER)

    def test_role_to_permission_parity(self) -> None:
        """For every role x permission: the model unions the role into `can_*` iff RBAC grants it."""
        relations = _org_type()["relations"]
        for role in ROLE_ORDER:
            granted = set(SYSTEM_ROLES[role]["permissions"])  # type: ignore[arg-type]
            for perm in PERMISSIONS:
                definition = relations[relation_for(perm.key)]
                children = definition.get("union", {}).get("child", [definition])
                computed = {c["computedUserset"]["relation"] for c in children if "computedUserset" in c}
                assert (role in computed) == (perm.key in granted), (role, perm.key)

    def test_direct_user_grants_for_custom_roles(self) -> None:
        metadata = _org_type()["metadata"]["relations"]
        for perm in PERMISSIONS:
            assert metadata[relation_for(perm.key)]["directly_related_user_types"] == [{"type": "user"}]

    def test_operator_permission_has_no_role(self) -> None:
        assert roles_holding("entitlement:manage") == []  # ADR 0008: only direct grants / platform admin

    def test_project_template(self) -> None:
        project = next(t for t in build_model()["type_definitions"] if t["type"] == "project")
        assert set(project["relations"]) == {"org", "viewer", "editor"}
        viewer = project["relations"]["viewer"]["union"]["child"]
        assert any("tupleToUserset" in c for c in viewer)  # inherits from the org's can_project_read

    def test_dsl_renders_the_same_model(self) -> None:
        dsl = render_dsl()
        assert dsl.startswith("model\n  schema 1.1")
        assert "type organization" in dsl and "type project" in dsl
        for perm in PERMISSIONS:
            assert f"define {relation_for(perm.key)}: [user]" in dsl
        assert "define can_org_delete: [user] or owner\n" in dsl
        assert "define can_billing_read: [user] or owner or admin or billing\n" in dsl
        assert "define viewer: [user] or editor or can_project_read from org" in dsl

    def test_model_is_json_serialisable(self) -> None:
        import json

        json.dumps(build_model())
