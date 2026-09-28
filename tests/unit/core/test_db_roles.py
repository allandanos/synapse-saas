"""Engine routing and role provisioning guards (no database)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from synapse_saas.core import db as core_db
from synapse_saas.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_engines(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    for name in ("_engine", "_session_factory", "_owner_engine", "_owner_session_factory"):
        monkeypatch.setattr(core_db, name, None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestOwnerEngineRouting:
    def test_owner_engine_is_request_engine_without_worker_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SYNAPSE_WORKER_DATABASE_URL", raising=False)
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:1/x")
        get_settings.cache_clear()
        assert core_db.get_owner_engine() is core_db.get_engine()
        assert core_db.get_owner_session_factory() is core_db.get_session_factory()

    def test_owner_engine_is_separate_with_worker_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:1/x")
        monkeypatch.setenv("SYNAPSE_WORKER_DATABASE_URL", "postgresql+asyncpg://owner:owner@localhost:1/x")
        get_settings.cache_clear()
        app_engine = core_db.get_engine()
        owner_engine = core_db.get_owner_engine()
        assert owner_engine is not app_engine
        assert owner_engine.url.username == "owner"
        assert app_engine.url.username == "app"
        assert core_db.get_owner_session_factory() is not core_db.get_session_factory()

    async def test_dispose_clears_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:1/x")
        monkeypatch.setenv("SYNAPSE_WORKER_DATABASE_URL", "postgresql+asyncpg://owner:owner@localhost:1/x")
        get_settings.cache_clear()
        core_db.get_engine()
        core_db.get_owner_engine()
        await core_db.dispose_engine()
        assert core_db._engine is None
        assert core_db._owner_engine is None


class TestProvisionGuards:
    async def test_rejects_unsafe_role_name(self) -> None:
        with pytest.raises(ValueError, match="role must match"):
            await core_db.provision_app_role(object(), "bad role; DROP TABLE x", "pw")  # type: ignore[arg-type]

    def test_cli_rejects_unsafe_role_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.cli import cli

        monkeypatch.setenv("SYNAPSE_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:1/x")
        result = CliRunner().invoke(
            cli, ["db", "provision-app-role", "--role", "Bad-Role", "--password", "x"]
        )
        assert result.exit_code != 0
        assert "role must match" in result.output

    def test_cli_requires_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.cli import cli

        monkeypatch.delenv("SYNAPSE_APP_ROLE_PASSWORD", raising=False)
        result = CliRunner().invoke(cli, ["db", "provision-app-role"])
        assert result.exit_code != 0
        assert "password" in result.output.lower()


class TestRlsGucHelpersAreNoOpsWhenOff:
    async def test_helpers_skip_execute_in_app_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TENANT_ISOLATION", "app")
        get_settings.cache_clear()

        class Session:
            calls = 0

            async def execute(self, *a, **k):  # type: ignore[no-untyped-def]
                self.calls += 1

        s = Session()
        import uuid

        await core_db.set_rls_tenant(s, uuid.uuid4())  # type: ignore[arg-type]
        await core_db.set_rls_user(s, uuid.uuid4())  # type: ignore[arg-type]
        await core_db.set_rls_platform(s)  # type: ignore[arg-type]
        assert s.calls == 0

    async def test_helpers_execute_in_rls_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SYNAPSE_TENANT_ISOLATION", "app_and_rls")
        get_settings.cache_clear()
        seen: list[tuple[str, str]] = []

        class Session:
            async def execute(self, stmt, params):  # type: ignore[no-untyped-def]
                seen.append((params["name"], params["value"]))

        import uuid

        org, user = uuid.uuid4(), uuid.uuid4()
        await core_db.set_rls_tenant(Session(), org)  # type: ignore[arg-type]
        await core_db.set_rls_user(Session(), user)  # type: ignore[arg-type]
        await core_db.set_rls_platform(Session())  # type: ignore[arg-type]
        assert seen == [
            ("app.current_tenant", str(org)),
            ("app.current_user", str(user)),
            ("app.rls_platform", "on"),
        ]
