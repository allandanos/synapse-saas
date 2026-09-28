"""Row-level security is real: a subject DB role is policed by Postgres.

These tests provision the RLS-subject role on the scratch database and open a
second engine AS THAT ROLE, so they prove enforcement regardless of which role
the main suite runs under. `make test-rls` additionally runs the whole suite
as the subject role with SYNAPSE_TENANT_ISOLATION=app_and_rls.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from synapse_saas.core import db as core_db
from tests.integration.conftest import owner_engine

pytestmark = pytest.mark.pg

APP_ROLE = "synapse_rls_test"
APP_ROLE_PASSWORD = "synapse_rls_test"  # scratch DB only


def _as_role(url: str, role: str, password: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(
        (parts.scheme, f"{role}:{password}@{host}{port}", parts.path, parts.query, parts.fragment)
    )


@pytest_asyncio.fixture
async def app_role_engine(migrated_db) -> AsyncIterator[AsyncEngine]:
    """Engine connected as the RLS-subject role (provisioned by the owner).

    Function-scoped on purpose: every test gets its own event loop, and an
    engine (or a shared pool primed) on another loop breaks asyncpg.
    Provisioning is idempotent and cheap.
    """
    await core_db.provision_app_role(owner_engine(), APP_ROLE, APP_ROLE_PASSWORD)
    url = _as_role(os.environ["SYNAPSE_DATABASE_URL"], APP_ROLE, APP_ROLE_PASSWORD)
    # The owner may run the suite as the app role already (make test-rls); the
    # dedicated engine still proves the policies from a clean connection.
    engine = create_async_engine(url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


async def _two_orgs(client: AsyncClient) -> tuple[dict[str, str], dict[str, str]]:
    """Two users, two orgs, each with a subscription bootstrapped by the API."""
    orgs = []
    for label in ("alpha", "beta"):
        reg = await client.post(
            "/v1/auth/register",
            json={
                "email": f"rls-{label}-{uuid.uuid4().hex[:6]}@example.com",
                "password": "password12345",
                "display_name": label,
            },
        )
        assert reg.status_code == 201, reg.text
        tokens = reg.json()["tokens"]
        user_id = reg.json()["user"]["id"]
        org = await client.post(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={"name": f"RLS {label}"},
        )
        assert org.status_code == 201, org.text
        orgs.append({"org_id": org.json()["id"], "user_id": user_id, "token": tokens["access_token"]})
    return orgs[0], orgs[1]


class TestPolicyCoverage:
    async def test_every_tenant_table_has_a_policy(self, migrated_db) -> None:
        """Every ORM table with organization_id is policed unless explicitly excluded."""
        # Import every model module so Base.metadata is complete
        import synapse_saas.agents.models
        import synapse_saas.api_keys.models
        import synapse_saas.audit.models
        import synapse_saas.authorization.models
        import synapse_saas.billing.invoicing
        import synapse_saas.billing.models
        import synapse_saas.entitlements.models
        import synapse_saas.feature_flags.models
        import synapse_saas.identity.models
        import synapse_saas.storage.models
        import synapse_saas.subscriptions.models
        import synapse_saas.tenancy.models
        import synapse_saas.usage.models
        import synapse_saas.webhooks.models  # noqa: F401

        tenant_tables = {
            t.name for t in core_db.Base.metadata.tables.values() if "organization_id" in t.columns
        } - core_db.RLS_EXCLUDED_TABLES

        async with owner_engine().connect() as conn:
            policed = {
                row[0]
                for row in (
                    await conn.execute(
                        text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")
                    )
                ).all()
            }
            forced = {
                row[0]
                for row in (
                    await conn.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity"))
                ).all()
            }
        missing = tenant_tables - policed
        assert not missing, f"tenant tables without an RLS policy: {sorted(missing)}"
        # The owner (worker/CLI/migrations) must bypass: nothing may be FORCEd.
        assert not forced, f"FORCE ROW LEVEL SECURITY would lock out the owner role: {sorted(forced)}"


class TestSubjectRoleIsPoliced:
    async def test_zero_rows_without_any_guc(self, client: AsyncClient, app_role_engine: AsyncEngine) -> None:
        await _two_orgs(client)
        async with app_role_engine.connect() as conn:
            for table in ("memberships", "subscriptions", "audit_logs", "outbox_events"):
                # audit/outbox admit organization_id IS NULL rows (platform scope),
                # so assert on tenant rows specifically.
                stmt = text(f"SELECT count(*) FROM {table} WHERE organization_id IS NOT NULL")  # noqa: S608
                count = (await conn.execute(stmt)).scalar_one()
                assert count == 0, f"{table}: subject role saw {count} tenant rows with no GUC set"

    async def test_tenant_guc_scopes_to_one_org(
        self, client: AsyncClient, app_role_engine: AsyncEngine
    ) -> None:
        a, _b = await _two_orgs(client)
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(text("SELECT set_config('app.current_tenant', :o, true)"), {"o": a["org_id"]})
            rows = (
                await conn.execute(text("SELECT DISTINCT organization_id::text FROM subscriptions"))
            ).all()
            assert [r[0] for r in rows] == [a["org_id"]]
            members = (await conn.execute(text("SELECT organization_id::text FROM memberships"))).all()
            assert {r[0] for r in members} == {a["org_id"]}

    async def test_user_guc_reads_own_memberships_pre_tenant(
        self, client: AsyncClient, app_role_engine: AsyncEngine
    ) -> None:
        """/auth/me and org listing run before any tenant exists: the user clause must admit them."""
        a, _b = await _two_orgs(client)
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(text("SELECT set_config('app.current_user', :u, true)"), {"u": a["user_id"]})
            members = (
                await conn.execute(text("SELECT user_id::text, organization_id::text FROM memberships"))
            ).all()
            assert {r[0] for r in members} == {a["user_id"]}
            assert {r[1] for r in members} == {a["org_id"]}
            # …but not another tenant's subscription rows
            subs = (await conn.execute(text("SELECT count(*) FROM subscriptions"))).scalar_one()
            assert subs == 0

    async def test_platform_guc_sees_every_tenant(
        self, client: AsyncClient, app_role_engine: AsyncEngine
    ) -> None:
        a, b = await _two_orgs(client)
        async with app_role_engine.connect() as conn, conn.begin():
            await conn.execute(text("SELECT set_config('app.rls_platform', 'on', true)"))
            rows = (
                await conn.execute(text("SELECT DISTINCT organization_id::text FROM subscriptions"))
            ).all()
            assert {r[0] for r in rows} >= {a["org_id"], b["org_id"]}

    async def test_cross_tenant_write_is_rejected(
        self, client: AsyncClient, app_role_engine: AsyncEngine
    ) -> None:
        """WITH CHECK: bound to org A, an insert stamped with org B must fail."""
        a, b = await _two_orgs(client)
        async with app_role_engine.connect() as conn:
            with pytest.raises(DBAPIError, match="row-level security"):
                async with conn.begin():
                    await conn.execute(
                        text("SELECT set_config('app.current_tenant', :o, true)"), {"o": a["org_id"]}
                    )
                    await conn.execute(
                        text(
                            "INSERT INTO agents (id, organization_id, slug, name, status, config) "
                            "VALUES (:id, :org, 'smuggled', 'Smuggled', 'active', '{}'::jsonb)"
                        ),
                        {"id": str(uuid.uuid4()), "org": b["org_id"]},
                    )

    async def test_guc_is_transaction_local(self, client: AsyncClient, app_role_engine: AsyncEngine) -> None:
        """A pooled connection must not leak a tenant into the next transaction."""
        a, _b = await _two_orgs(client)
        async with app_role_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(
                    text("SELECT set_config('app.current_tenant', :o, true)"), {"o": a["org_id"]}
                )
                assert (await conn.execute(text("SELECT count(*) FROM subscriptions"))).scalar_one() == 1
            async with conn.begin():
                assert (await conn.execute(text("SELECT count(*) FROM subscriptions"))).scalar_one() == 0


class TestStartupGuard:
    async def test_subject_role_with_rls_off_is_refused(
        self, app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_TENANT_ISOLATION", "app")
        get_settings.cache_clear()
        monkeypatch.setattr(core_db, "_engine", app_role_engine)
        try:
            with pytest.raises(core_db.RoleIsolationMismatchError, match="subject to RLS"):
                await core_db.assert_role_matches_isolation()
        finally:
            get_settings.cache_clear()

    async def test_bypassing_role_with_rls_on_is_refused(
        self, migrated_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_TENANT_ISOLATION", "app_and_rls")
        get_settings.cache_clear()
        monkeypatch.setattr(core_db, "_engine", owner_engine())
        try:
            with pytest.raises(core_db.RoleIsolationMismatchError, match="bypasses RLS"):
                await core_db.assert_role_matches_isolation()
        finally:
            get_settings.cache_clear()

    async def test_subject_role_with_rls_on_is_accepted(
        self, app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_TENANT_ISOLATION", "app_and_rls")
        get_settings.cache_clear()
        monkeypatch.setattr(core_db, "_engine", app_role_engine)
        try:
            await core_db.assert_role_matches_isolation()
        finally:
            get_settings.cache_clear()
