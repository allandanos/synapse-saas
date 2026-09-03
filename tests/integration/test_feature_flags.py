"""Feature flags end-to-end: lifecycle, overrides, rollout, permissions."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
def _lift_rate_limits(monkeypatch: pytest.MonkeyPatch):
    """The rollout test registers 30 users in one go — lift the per-IP cap."""
    from synapse_saas.core import rate_limit as rl_module
    from synapse_saas.core.config import get_settings

    monkeypatch.setenv("SYNAPSE_AUTH_RATE_LIMIT_PER_IP", "1000")
    get_settings.cache_clear()
    rl_module.reset_rate_limiter()
    yield
    get_settings.cache_clear()
    rl_module.reset_rate_limiter()


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


async def make_platform_admin(client: AsyncClient, email: str) -> None:
    from sqlalchemy import select

    from synapse_saas.core.db import get_session_factory
    from synapse_saas.identity.models import User

    factory = get_session_factory()
    async with factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.is_platform_admin = True
        await session.commit()


class TestLifecycle:
    async def test_create_list_update(self, client: AsyncClient, org_and_tokens) -> None:
        await make_platform_admin(client, "owner@example.com")
        token = org_and_tokens["access_token"]
        admin = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "new-editor", "name": "New Editor", "enabled": False},
        )
        assert created.status_code == 201, created.text
        assert created.json()["key"] == "new-editor"

        listed = (await client.get("/v1/feature-flags", headers=admin)).json()
        assert any(f["key"] == "new-editor" for f in listed)

        updated = await client.patch("/v1/feature-flags/new-editor", headers=admin, json={"enabled": True})
        assert updated.status_code == 200
        assert updated.json()["enabled"] is True

    async def test_duplicate_key_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        await make_platform_admin(client, "owner@example.com")
        admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "dup-flag", "name": "Dup Flag"},
        )
        again = await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "dup-flag", "name": "Dup Flag 2"},
        )
        assert again.status_code == 404  # flag-not-found misuse class

    async def test_invalid_key_format_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        await make_platform_admin(client, "owner@example.com")
        res = await client.post(
            "/v1/feature-flags",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
            json={"key": "Bad Key!", "name": "X"},
        )
        assert res.status_code == 422


class TestEvaluation:
    async def test_unknown_flag_is_off(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/feature-flags/check/no-such-flag", headers=org_headers(org_and_tokens))
        assert res.status_code == 200
        assert res.json() == {"key": "no-such-flag", "enabled": False}

    async def test_global_default(self, client: AsyncClient, org_and_tokens) -> None:
        await make_platform_admin(client, "owner@example.com")
        admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "dark-launch", "name": "Dark Launch", "enabled": True},
        )
        res = await client.get("/v1/feature-flags/check/dark-launch", headers=org_headers(org_and_tokens))
        assert res.json()["enabled"] is True

    async def test_org_override_wins(self, client: AsyncClient, org_and_tokens) -> None:
        await make_platform_admin(client, "owner@example.com")
        admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "beta-ui", "name": "Beta UI", "enabled": False},
        )
        # Off globally, on for this org
        await client.post(
            "/v1/feature-flags/beta-ui/overrides",
            headers=admin,
            json={"organization_id": org_and_tokens["org_id"], "enabled": True},
        )
        res = await client.get("/v1/feature-flags/check/beta-ui", headers=org_headers(org_and_tokens))
        assert res.json()["enabled"] is True

    async def test_org_override_delete_restores_default(self, client: AsyncClient, org_and_tokens) -> None:
        await make_platform_admin(client, "owner@example.com")
        admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "temp-on", "name": "Temp", "enabled": False},
        )
        created = await client.post(
            "/v1/feature-flags/temp-on/overrides",
            headers=admin,
            json={"organization_id": org_and_tokens["org_id"], "enabled": True},
        )
        override_id = created.json()["id"]

        removed = await client.delete(f"/v1/feature-flags/overrides/{override_id}", headers=admin)
        assert removed.status_code == 204
        res = await client.get("/v1/feature-flags/check/temp-on", headers=org_headers(org_and_tokens))
        assert res.json()["enabled"] is False

    async def test_user_override_beats_org_override(self, client: AsyncClient, org_and_tokens) -> None:
        from sqlalchemy import select

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.identity.models import User

        await make_platform_admin(client, "owner@example.com")
        admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={"key": "layered", "name": "Layered", "enabled": False},
        )
        async with get_session_factory()() as session:
            user = (await session.execute(select(User).where(User.email == "owner@example.com"))).scalar_one()
            user_id = user.id

        # org: on; user: off ⇒ user wins
        await client.post(
            "/v1/feature-flags/layered/overrides",
            headers=admin,
            json={"organization_id": org_and_tokens["org_id"], "enabled": True},
        )
        await client.post(
            "/v1/feature-flags/layered/overrides",
            headers=admin,
            json={"user_id": str(user_id), "enabled": False},
        )
        res = await client.get("/v1/feature-flags/check/layered", headers=org_headers(org_and_tokens))
        assert res.json()["enabled"] is False


class TestRolloutApi:
    async def test_rollout_partitions_orgs(self, client: AsyncClient, org_and_tokens) -> None:
        """50% rollout: across 30 orgs both states appear, each org stable."""
        await make_platform_admin(client, "owner@example.com")
        admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        await client.post(
            "/v1/feature-flags",
            headers=admin,
            json={
                "key": "gradual",
                "name": "Gradual Rollout",
                "enabled": False,
                "rollout_percentage": 50,
            },
        )

        results = []
        for i in range(30):
            reg = await client.post(
                "/v1/auth/register",
                json={
                    "email": f"rollout{i}@example.com",
                    "password": "password12345",
                    "display_name": f"R{i}",
                },
            )
            token = reg.json()["tokens"]["access_token"]
            org = (
                await client.post(
                    "/v1/orgs",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": f"Rollout Org {i}"},
                )
            ).json()["id"]
            res = await client.get(
                "/v1/feature-flags/check/gradual",
                headers={"Authorization": f"Bearer {token}", "X-Org-Id": org},
            )
            results.append(res.json()["enabled"])

        assert any(results) and not all(results)  # both sides present
        # Stability: re-check a few — same answers
        for i in (0, 1, 2):
            reg = await client.post(
                "/v1/auth/login",
                json={"email": f"rollout{i}@example.com", "password": "password12345"},
            )
            token = reg.json()["tokens"]["access_token"]
            orgs = (await client.get("/v1/orgs", headers={"Authorization": f"Bearer {token}"})).json()["data"]
            res = await client.get(
                "/v1/feature-flags/check/gradual",
                headers={"Authorization": f"Bearer {token}", "X-Org-Id": orgs[0]["id"]},
            )
            assert res.json()["enabled"] == results[i]


class TestPermissions:
    async def test_management_requires_platform_admin(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/feature-flags", headers=org_headers(org_and_tokens))
        assert res.status_code == 404  # platform gate denies as not-found

    async def test_evaluation_needs_org_context(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get(
            "/v1/feature-flags/check/some-flag",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
        )
        assert res.status_code == 404


class TestRequireFlagGate:
    async def test_gate_dependency_direct(self, client: AsyncClient, org_and_tokens) -> None:
        """require_flag resolves through the same service the check endpoint uses:
        off for unknown flags, on after an org override — no dynamic routes needed."""
        from synapse_saas.core import context
        from synapse_saas.core.db import get_session_factory
        from synapse_saas.core.errors import PermissionDeniedError
        from synapse_saas.feature_flags.dependencies import require_flag_dependency
        from synapse_saas.identity.dependencies import get_current_user
        from synapse_saas.tenancy.dependencies import resolve_tenant

        factory = get_session_factory()
        async with factory() as session:
            user = await get_current_user(
                _FakeRequest(org_id=org_and_tokens["org_id"], token=org_and_tokens["access_token"]),
                session,
            )
            token_ctx = await resolve_tenant(
                _FakeRequest(org_id=org_and_tokens["org_id"], token=org_and_tokens["access_token"]),
                user,
                session,
            )
            from uuid import UUID

            from synapse_saas.core.context import TenantContext

            assert isinstance(token_ctx, TenantContext)

            # Unknown flag ⇒ denied with flag context
            with pytest.raises(PermissionDeniedError) as exc_info:
                await require_flag_dependency("gate-probe", user, token_ctx, session)
            assert exc_info.value.extras["flag"] == "gate-probe"

            # Create + org-override on ⇒ allowed
            await make_platform_admin(client, "owner@example.com")
            admin = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
            await client.post(
                "/v1/feature-flags",
                headers=admin,
                json={"key": "gate-probe", "name": "Gate Probe", "enabled": False},
            )
            await client.post(
                "/v1/feature-flags/gate-probe/overrides",
                headers=admin,
                json={"organization_id": org_and_tokens["org_id"], "enabled": True},
            )
            context._tenant.set(None)  # ensure no stale scope confuses re-resolution
            result = await require_flag_dependency(
                "gate-probe",
                user,
                TenantContext(organization_id=UUID(org_and_tokens["org_id"]), slug="t"),
                session,
            )
            assert result is not None


class _FakeRequest:
    """Minimal request stand-in for dependency functions."""

    def __init__(self, org_id: str, token: str) -> None:
        self.headers = {
            "Authorization": f"Bearer {token}",
            "X-Org-Id": org_id,
            "host": "testserver",
        }
        self.url = type("U", (), {"path": "/probe"})()
