"""Backend dispatch: RBAC by default, OpenFGA when configured, explicit failure modes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from synapse_saas.authorization import service as service_module
from synapse_saas.authorization.fga import FgaError, Tuple
from synapse_saas.authorization.sync import desired_tuples


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    from synapse_saas.core import cache as cache_module

    backend = cache_module.TTLDictBackend()
    monkeypatch.setattr(cache_module, "_backend", lambda: backend)


@pytest.fixture
def openfga(monkeypatch: pytest.MonkeyPatch):
    from synapse_saas.core.config import get_settings

    monkeypatch.setenv("SYNAPSE_AUTHZ_BACKEND", "openfga")
    monkeypatch.setenv("SYNAPSE_OPENFGA_URL", "http://fga.test")
    monkeypatch.setenv("SYNAPSE_OPENFGA_STORE_ID", "st")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeFga:
    """Stands in for FgaClient inside the service module."""

    calls: list[tuple[str, str, str]] = []
    answer: bool | Exception = True

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def check(self, user: str, relation: str, obj: str) -> bool:
        FakeFga.calls.append((user, relation, obj))
        if isinstance(FakeFga.answer, Exception):
            raise FakeFga.answer
        return FakeFga.answer


class FakeSession:
    info: dict[str, Any] = {}


@pytest.fixture
def fake_fga(monkeypatch: pytest.MonkeyPatch) -> type[FakeFga]:
    FakeFga.calls = []
    FakeFga.answer = True
    monkeypatch.setattr(service_module, "FgaClient", FakeFga)
    return FakeFga


async def _rbac_keys(*_: Any, **__: Any) -> frozenset[str]:
    return frozenset({"org:read"})


class TestDispatch:
    async def test_rbac_is_the_default(
        self, monkeypatch: pytest.MonkeyPatch, fake_fga: type[FakeFga]
    ) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        monkeypatch.setattr(svc, "permission_keys_for", _rbac_keys)
        assert await svc.user_can(uuid4(), uuid4(), "org:read") is True
        assert await svc.user_can(uuid4(), uuid4(), "org:delete") is False
        assert fake_fga.calls == []  # never consulted

    async def test_openfga_asks_the_store_with_catalog_relations(
        self, openfga, fake_fga: type[FakeFga]
    ) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        user, org = uuid4(), uuid4()
        fake_fga.answer = False
        assert await svc.user_can(user, org, "org:delete") is False
        assert fake_fga.calls == [(f"user:{user}", "can_org_delete", f"organization:{org}")]

    async def test_decisions_are_cached_per_user_object(self, openfga, fake_fga: type[FakeFga]) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        user, org = uuid4(), uuid4()
        await svc.user_can(user, org, "org:read")
        await svc.user_can(user, org, "org:read")
        assert len(fake_fga.calls) == 1
        await svc.user_can(user, org, "org:update")  # a different permission is a different question
        assert len(fake_fga.calls) == 2

    async def test_resource_level_check(self, openfga, fake_fga: type[FakeFga]) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        user = uuid4()
        assert await svc.user_can_on(user, "project:manage", "project", "p-1") is True
        assert fake_fga.calls == [(f"user:{user}", "can_project_manage", "project:p-1")]

    async def test_rbac_backend_refuses_non_org_resources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError):
            await svc.user_can_on(uuid4(), "project:manage", "project", "p-1")


class TestFailureModes:
    async def test_closed_denies_on_outage(self, openfga, fake_fga: type[FakeFga], monkeypatch) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        monkeypatch.setattr(svc, "permission_keys_for", _rbac_keys)
        fake_fga.answer = FgaError("down")
        assert await svc.user_can(uuid4(), uuid4(), "org:read") is False  # RBAC would say yes

    async def test_rbac_fallback_on_outage(self, openfga, fake_fga: type[FakeFga], monkeypatch) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_OPENFGA_FAIL_MODE", "rbac")
        get_settings.cache_clear()
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        monkeypatch.setattr(svc, "permission_keys_for", _rbac_keys)
        fake_fga.answer = FgaError("down")
        assert await svc.user_can(uuid4(), uuid4(), "org:read") is True
        assert await svc.user_can(uuid4(), uuid4(), "org:delete") is False

    async def test_outages_are_never_cached(self, openfga, fake_fga: type[FakeFga], monkeypatch) -> None:
        svc = service_module.AuthorizationService(FakeSession())  # type: ignore[arg-type]
        monkeypatch.setattr(svc, "permission_keys_for", _rbac_keys)
        user, org = uuid4(), uuid4()
        fake_fga.answer = FgaError("down")
        assert await svc.user_can(user, org, "org:read") is False
        fake_fga.answer = True
        assert await svc.user_can(user, org, "org:read") is True  # recovered ⇒ asked again


class TestDesiredTuples:
    def test_system_roles_become_role_tuples(self) -> None:
        user, org = uuid4(), uuid4()
        tuples = desired_tuples(
            user_id=user, organization_id=org, role_keys=["admin"], permission_keys=["org:read", "org:update"]
        )
        assert tuples == {Tuple(f"user:{user}", "admin", f"organization:{org}")}

    def test_custom_role_permissions_become_direct_grants(self) -> None:
        user, org = uuid4(), uuid4()
        tuples = desired_tuples(
            user_id=user,
            organization_id=org,
            role_keys=["member", "auditor"],  # auditor is a custom role granting audit:read
            permission_keys=["org:read", "project:read", "audit:read"],
        )
        assert tuples == {
            Tuple(f"user:{user}", "member", f"organization:{org}"),
            Tuple(f"user:{user}", "can_audit_read", f"organization:{org}"),
        }

    def test_no_roles_means_no_tuples(self) -> None:
        assert (
            desired_tuples(user_id=uuid4(), organization_id=uuid4(), role_keys=[], permission_keys=[])
            == set()
        )
