"""Against a REAL OpenFGA (CI job `integration-fga`; locally: docker compose
--profile extras up -d openfga + SYNAPSE_OPENFGA_URL=http://localhost:8081).

1. The generated model answers every system role x permission exactly like RBAC.
2. With SYNAPSE_AUTHZ_BACKEND=openfga, a route is gated by the store and the
   tuple sync (outbox → worker) converges after a role change.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from synapse_saas.authorization.fga import FgaClient, Tuple
from synapse_saas.authorization.fga_model import ROLE_ORDER, build_model, relation_for
from synapse_saas.authorization.permissions import PERMISSIONS, SYSTEM_ROLES

pytestmark = [pytest.mark.pg, pytest.mark.fga]

FGA_URL = os.environ.get("SYNAPSE_OPENFGA_URL", "")

if not FGA_URL:
    pytest.skip("SYNAPSE_OPENFGA_URL not set", allow_module_level=True)


@pytest.fixture
async def store(monkeypatch: pytest.MonkeyPatch) -> FgaClient:
    """A fresh store with the generated model, exported to the settings."""
    from synapse_saas.core.config import get_settings

    http = httpx.AsyncClient()
    client = FgaClient(url=FGA_URL, store_id="", http=http)
    client.store_id = await client.create_store(f"synapse-test-{uuid4().hex[:8]}")
    client.model_id = await client.write_model(build_model())
    monkeypatch.setenv("SYNAPSE_OPENFGA_URL", FGA_URL)
    monkeypatch.setenv("SYNAPSE_OPENFGA_STORE_ID", client.store_id)
    monkeypatch.setenv("SYNAPSE_OPENFGA_MODEL_ID", client.model_id)
    get_settings.cache_clear()
    yield client
    await http.aclose()
    get_settings.cache_clear()


class TestModelParity:
    async def test_every_role_times_permission_matches_rbac(self, store: FgaClient) -> None:
        org = f"organization:{uuid4()}"
        users = {role: f"user:{uuid4()}" for role in ROLE_ORDER}
        await store.write(writes=[Tuple(users[role], role, org) for role in ROLE_ORDER])
        mismatches = []
        for role in ROLE_ORDER:
            granted = set(SYSTEM_ROLES[role]["permissions"])  # type: ignore[arg-type]
            for perm in PERMISSIONS:
                allowed = await store.check(users[role], relation_for(perm.key), org)
                if allowed != (perm.key in granted):
                    mismatches.append((role, perm.key, allowed))
        assert mismatches == []

    async def test_direct_grant_and_project_inheritance(self, store: FgaClient) -> None:
        org, user, project = f"organization:{uuid4()}", f"user:{uuid4()}", f"project:{uuid4()}"
        await store.write(
            writes=[
                Tuple(user, "member", org),  # member: project:read only
                Tuple(user, "can_audit_read", org),  # a custom role's direct grant
                Tuple(org, "org", project),
            ]
        )
        assert await store.check(user, "can_audit_read", org)
        assert await store.check(user, "viewer", project)  # inherited via can_project_read from org
        assert not await store.check(user, "editor", project)
        await store.write(writes=[Tuple(user, "editor", project)])  # shared explicitly
        assert await store.check(user, "editor", project)


class TestEndToEnd:
    async def test_route_gated_by_the_store_and_sync_converges(
        self, store: FgaClient, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_AUTHZ_BACKEND", "openfga")
        get_settings.cache_clear()
        headers = {
            "Authorization": f"Bearer {org_and_tokens['access_token']}",
            "X-Org-Id": org_and_tokens["org_id"],
        }

        # Nothing synced yet ⇒ closed: even the owner is denied
        denied = await client.get("/v1/orgs/current/members", headers=headers)
        assert denied.status_code == 403, denied.text

        # Backfill the owner's tuples (what `synapse-cli authz fga sync --all` does)
        from synapse_saas.authorization.sync import apply_tuple_sync

        me = (await client.get("/v1/auth/me", headers=headers)).json()
        result = await apply_tuple_sync({"organization_id": org_and_tokens["org_id"], "user_id": me["id"]})
        assert result["writes"] >= 1
        from synapse_saas.core.cache import VersionedCache

        await VersionedCache("fga").bump(f"{me['id']}:organization:{org_and_tokens['org_id']}")
        allowed = await client.get("/v1/orgs/current/members", headers=headers)
        assert allowed.status_code == 200, allowed.text

        # A role change queues a resync; the worker applies it; the store reflects it
        from sqlalchemy import text

        from synapse_saas.worker.jobs import dispatch_outbox
        from tests.integration.conftest import owner_session_factory

        inv = await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "d@example.com"}
        )
        reg = await client.post(
            "/v1/auth/register",
            json={"email": "d@example.com", "password": "password12345", "display_name": "D"},
        )
        from uuid import UUID

        from synapse_saas.tenancy.service import OrganizationService

        async with owner_session_factory()() as session:
            await OrganizationService(session).accept_invite_by_email(
                UUID(org_and_tokens["org_id"]), "d@example.com"
            )
            await session.commit()
        await dispatch_outbox({})
        dev_id = reg.json()["user"]["id"]
        assert await store.check(f"user:{dev_id}", "member", f"organization:{org_and_tokens['org_id']}")
        assert not await store.check(
            f"user:{dev_id}", "can_org_delete", f"organization:{org_and_tokens['org_id']}"
        )

        # Promote to admin ⇒ resync ⇒ the store now says yes to admin things
        patched = await client.patch(
            f"/v1/memberships/{inv.json()['id']}", headers=headers, json={"role_keys": ["admin"]}
        )
        assert patched.status_code == 200, patched.text
        await dispatch_outbox({})
        assert await store.check(f"user:{dev_id}", "admin", f"organization:{org_and_tokens['org_id']}")
        assert not await store.check(f"user:{dev_id}", "member", f"organization:{org_and_tokens['org_id']}")
        async with owner_session_factory()() as session:
            dead = (
                await session.execute(text("SELECT count(*) FROM outbox_events WHERE dead_at IS NOT NULL"))
            ).scalar_one()
        assert dead == 0
