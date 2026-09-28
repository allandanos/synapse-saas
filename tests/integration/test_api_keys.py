"""API keys end-to-end: CRUD, auth as org, scopes, lifecycle, isolation."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import owner_session_factory

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


async def create_key(client: AsyncClient, fixture: dict[str, str], **overrides: object) -> tuple[str, str]:
    """Returns (key_id, plaintext)."""
    body: dict[str, object] = {"name": "test key"}
    body.update(overrides)
    res = await client.post("/v1/api-keys", headers=org_headers(fixture), json=body)
    assert res.status_code == 201, res.text
    data = res.json()
    return data["id"], data["key"]


class TestCrud:
    async def test_create_returns_plaintext_once(self, client: AsyncClient, org_and_tokens) -> None:
        key_id, plaintext = await create_key(client, org_and_tokens, name="ci")
        assert plaintext.startswith("sk_")
        assert len(plaintext) > 40

        # List shows prefix only — never the plaintext again
        listed = (await client.get("/v1/api-keys", headers=org_headers(org_and_tokens))).json()
        match = [k for k in listed if k["id"] == key_id]
        assert match
        assert match[0]["prefix"] == plaintext[:8]
        assert "key" not in match[0]

    async def test_revoke(self, client: AsyncClient, org_and_tokens) -> None:
        key_id, _ = await create_key(client, org_and_tokens)
        res = await client.delete(f"/v1/api-keys/{key_id}", headers=org_headers(org_and_tokens))
        assert res.status_code == 204
        listed = (await client.get("/v1/api-keys", headers=org_headers(org_and_tokens))).json()
        assert next(k for k in listed if k["id"] == key_id)["revoked_at"] is not None

    async def test_unknown_scope_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/api-keys",
            headers=org_headers(org_and_tokens),
            json={"name": "bad", "scopes": ["not:a:scope"]},
        )
        assert res.status_code == 403
        assert "not:a:scope" in res.json()["detail"]

    async def test_cross_org_key_404(self, client: AsyncClient, org_and_tokens) -> None:
        """Revoking another org's key id → 404, identical to nonexistent."""
        key_id, _ = await create_key(client, org_and_tokens)
        other = await client.post(
            "/v1/auth/register",
            json={
                "email": "keyrival@example.com",
                "password": "password12345",
                "display_name": "R",
            },
        )
        other_token = other.json()["tokens"]["access_token"]

        # No org context → tenant resolution 404s before the key is touched
        res = await client.delete(
            f"/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert res.status_code == 404

        # With the rival's own org context, the foreign key id is a plain 404
        # — byte-identical to a nonexistent id (no existence leak).
        rival_org = await client.post(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {other_token}"},
            json={"name": "Rival Org"},
        )
        rival_org_id = rival_org.json()["id"]
        foreign = await client.delete(
            f"/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {other_token}", "X-Org-Id": rival_org_id},
        )
        phantom = await client.delete(
            f"/v1/api-keys/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {other_token}", "X-Org-Id": rival_org_id},
        )
        assert foreign.status_code == phantom.status_code == 404
        # Bodies match except `instance` (the path echoes the requested id)
        foreign_body, phantom_body = foreign.json(), phantom.json()
        foreign_body.pop("instance"), phantom_body.pop("instance")
        assert foreign_body == phantom_body


class TestKeyAuth:
    async def test_key_authenticates_org_routes(self, client: AsyncClient, org_and_tokens) -> None:
        """sk_ bearer hits org endpoints with no X-Org-Id and no user token."""
        _, plaintext = await create_key(client, org_and_tokens)
        res = await client.get("/v1/entitlements", headers={"Authorization": f"Bearer {plaintext}"})
        assert res.status_code == 200, res.text
        assert res.json()["plan_key"] == "free"

    async def test_key_works_with_usage_endpoints(self, client: AsyncClient, org_and_tokens) -> None:
        _, plaintext = await create_key(client, org_and_tokens)
        res = await client.get(
            "/v1/usage/check",
            headers={"Authorization": f"Bearer {plaintext}"},
            params={"metric": "api_requests"},
        )
        assert res.status_code == 200
        # The key-authed call itself metered one api_requests unit
        assert res.json()["used"] >= 1

    async def test_scoped_key_denied_out_of_scope(self, client: AsyncClient, org_and_tokens) -> None:
        """A usage:read-only key cannot manage members."""
        _, plaintext = await create_key(client, org_and_tokens, name="ro", scopes=["usage:read"])
        allowed = await client.get("/v1/usage/summary", headers={"Authorization": f"Bearer {plaintext}"})
        assert allowed.status_code == 200

        denied = await client.post(
            "/v1/orgs/current/members/invite",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"email": "x@example.com"},
        )
        assert denied.status_code == 403
        assert denied.json().get("auth") == "api_key"

    async def test_empty_scopes_mean_full_access(self, client: AsyncClient, org_and_tokens) -> None:
        _, plaintext = await create_key(client, org_and_tokens, name="full")
        res = await client.get("/v1/api-keys", headers={"Authorization": f"Bearer {plaintext}"})
        assert res.status_code == 200

    async def test_revoked_key_401(self, client: AsyncClient, org_and_tokens) -> None:
        key_id, plaintext = await create_key(client, org_and_tokens)
        await client.delete(f"/v1/api-keys/{key_id}", headers=org_headers(org_and_tokens))

        res = await client.get("/v1/entitlements", headers={"Authorization": f"Bearer {plaintext}"})
        assert res.status_code == 401
        assert res.json()["type"].endswith("/unauthorized")

    async def test_expired_key_401(self, client: AsyncClient, org_and_tokens) -> None:
        _, plaintext = await create_key(client, org_and_tokens, name="short", expires_in_days=1)
        # Backdate past expiry
        from sqlalchemy import text

        async with owner_session_factory()() as session:
            await session.execute(text("UPDATE api_keys SET expires_at = now() - interval '1 hour'"))
            await session.commit()

        res = await client.get("/v1/entitlements", headers={"Authorization": f"Bearer {plaintext}"})
        assert res.status_code == 401

    async def test_garbage_key_401(self, client: AsyncClient) -> None:
        res = await client.get(
            "/v1/entitlements", headers={"Authorization": "Bearer sk_totally-made-up-key-xyz"}
        )
        assert res.status_code == 401


class TestTenantIsolation:
    async def test_key_cannot_target_other_org(self, client: AsyncClient, org_and_tokens) -> None:
        """A key's tenant is pinned; X-Org-Id for a foreign org is ignored."""
        _, plaintext = await create_key(client, org_and_tokens)
        foreign = str(uuid.uuid4())
        res = await client.get(
            "/v1/entitlements",
            headers={"Authorization": f"Bearer {plaintext}", "X-Org-Id": foreign},
        )
        assert res.status_code == 200  # served the KEY's org, not the header's
        body = res.json()
        assert body["organization_id"] == org_and_tokens["org_id"]


class TestAudit:
    async def test_key_events_audited(self, client: AsyncClient, org_and_tokens) -> None:
        await create_key(client, org_and_tokens, name="audited")
        audit = (await client.get("/v1/audit", headers=org_headers(org_and_tokens))).json()
        events = [e["event_type"] for e in audit["data"]]
        assert "api_key.created" in events


# ── C4: a key can never exceed its creator ────────────────────────────────────


async def _register(client: AsyncClient, email: str) -> dict[str, str]:
    reg = await client.post(
        "/v1/auth/register", json={"email": email, "password": "password12345", "display_name": "M"}
    )
    assert reg.status_code == 201, reg.text
    return {"access_token": reg.json()["tokens"]["access_token"]}


async def _add_member(client: AsyncClient, owner: dict[str, str], email: str, role: str) -> dict[str, str]:
    """Invite `email` with `role`, link the (already registered) user, return their org headers."""
    member = await _register(client, email)
    inv = await client.post(
        "/v1/orgs/current/members/invite",
        headers=org_headers(owner),
        json={"email": email, "role_keys": [role]},
    )
    assert inv.status_code == 201, inv.text
    from synapse_saas.tenancy.service import OrganizationService

    async with owner_session_factory()() as session:
        await OrganizationService(session).accept_invite_by_email(uuid.UUID(owner["org_id"]), email)
        await session.commit()
    return {"access_token": member["access_token"], "org_id": owner["org_id"]}


async def _membership_id(client: AsyncClient, owner: dict[str, str], email: str) -> str:
    members = (await client.get("/v1/orgs/current/members", headers=org_headers(owner))).json()
    rows = members["data"]
    return next(m["id"] for m in rows if m.get("email") == email)


class TestKeysAreBoundedByCreator:
    async def test_empty_scopes_snapshot_creator_not_everything(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        dev = await _add_member(client, org_and_tokens, "dev@example.com", "developer")
        res = await client.post("/v1/api-keys", headers=org_headers(dev), json={"name": "dev key"})
        assert res.status_code == 201, res.text
        from synapse_saas.authorization.permissions import SYSTEM_ROLES

        assert sorted(res.json()["scopes"]) == SYSTEM_ROLES["developer"]["permissions"]

    async def test_scope_superset_rejected_403(self, client: AsyncClient, org_and_tokens) -> None:
        dev = await _add_member(client, org_and_tokens, "dev2@example.com", "developer")
        res = await client.post(
            "/v1/api-keys", headers=org_headers(dev), json={"name": "escalate", "scopes": ["org:delete"]}
        )
        assert res.status_code == 403
        assert res.json()["exceeds_creator"] == ["org:delete"]

    async def test_developer_key_cannot_manage_billing(self, client: AsyncClient, org_and_tokens) -> None:
        dev = await _add_member(client, org_and_tokens, "dev3@example.com", "developer")
        _, plaintext = await create_key(client, dev, name="dev")
        res = await client.post(
            "/v1/subscription/change",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"plan_key": "pro"},
        )
        assert res.status_code == 403
        assert res.json()["auth"] == "api_key"

    async def test_demoting_the_creator_shrinks_the_key(self, client: AsyncClient, org_and_tokens) -> None:
        dev = await _add_member(client, org_and_tokens, "dev4@example.com", "developer")
        _, plaintext = await create_key(client, dev, name="dev")
        key_headers = {"Authorization": f"Bearer {plaintext}"}
        assert (await client.get("/v1/api-keys", headers=key_headers)).status_code == 200  # apikey:manage

        mid = await _membership_id(client, org_and_tokens, "dev4@example.com")
        demote = await client.patch(
            f"/v1/memberships/{mid}", headers=org_headers(org_and_tokens), json={"role_keys": ["member"]}
        )
        assert demote.status_code == 200, demote.text

        res = await client.get("/v1/api-keys", headers=key_headers)
        assert res.status_code == 403
        assert res.json()["reason"] == "creator_lacks_permission"

    async def test_key_minted_by_key_is_bounded_by_the_human(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        dev = await _add_member(client, org_and_tokens, "dev5@example.com", "developer")
        _, parent = await create_key(client, dev, name="parent")
        parent_headers = {"Authorization": f"Bearer {parent}"}

        child = await client.post("/v1/api-keys", headers=parent_headers, json={"name": "child"})
        assert child.status_code == 201, child.text
        from synapse_saas.authorization.permissions import SYSTEM_ROLES

        assert sorted(child.json()["scopes"]) == SYSTEM_ROLES["developer"]["permissions"]

        escalate = await client.post(
            "/v1/api-keys", headers=parent_headers, json={"name": "child2", "scopes": ["billing:manage"]}
        )
        assert escalate.status_code == 403

        # The audit row is attributed to the human behind the key, never the key's sentinel user id
        dev_bearer = {"Authorization": f"Bearer {dev['access_token']}"}
        me = (await client.get("/v1/auth/me", headers=dev_bearer)).json()
        from sqlalchemy import text

        async with owner_session_factory()() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT actor_type, actor_user_id::text, diff->>'api_key_id' AS key_id "
                        "FROM audit_logs WHERE event_type = 'api_key.created' AND target_id = :tid"
                    ),
                    {"tid": child.json()["id"]},
                )
            ).one()
        assert row.actor_type == "api_key"
        assert row.actor_user_id == me["id"]
        assert row.key_id is not None

    async def test_owner_key_with_explicit_scopes_stays_within_them(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        _, plaintext = await create_key(client, org_and_tokens, name="ro", scopes=["org:read"])
        res = await client.post(
            "/v1/api-keys", headers={"Authorization": f"Bearer {plaintext}"}, json={"name": "x"}
        )
        assert res.status_code == 403
        assert res.json()["permission"] == "apikey:manage"
