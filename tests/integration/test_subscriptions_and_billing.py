"""Subscription lifecycle + billing service integration tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


class TestTrialFlow:
    async def test_start_trial_changes_plan(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        res = await client.post("/v1/subscription/trial", headers=headers, json={"plan_key": "starter"})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["status"] == "trialing"
        assert body["trial_ends_at"] is not None

        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert ent["subscription_status"] == "trialing"
        assert ent["plan_key"] == "starter"
        assert "reports" in ent["features"]  # trial gets full plan features

    async def test_double_trial_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/trial", headers=headers, json={"plan_key": "starter"})
        again = await client.post("/v1/subscription/trial", headers=headers, json={"plan_key": "pro"})
        assert again.status_code == 409

    async def test_no_trial_plan_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        """free has trial_days=0 → TrialNotAllowedError."""
        res = await client.post(
            "/v1/subscription/trial",
            headers=org_headers(org_and_tokens),
            json={"plan_key": "free"},
        )
        assert res.status_code == 409


class TestCancelResume:
    async def test_cancel_at_period_end_then_resume(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})

        cancelled = await client.post(
            "/v1/subscription/cancel",
            headers=headers,
            json={"at_period_end": True},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["cancel_at_period_end"] is True

        resumed = await client.post("/v1/subscription/resume", headers=headers)
        assert resumed.status_code == 200
        assert resumed.json()["cancel_at_period_end"] is False

    async def test_cancel_immediately(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        res = await client.post(
            "/v1/subscription/cancel",
            headers=headers,
            json={"at_period_end": False},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "canceled"

        # Entitlements collapse after cancellation
        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert ent["features"] == []

    async def test_resume_without_pending_cancel_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post("/v1/subscription/resume", headers=org_headers(org_and_tokens))
        assert res.status_code == 404


class TestManualBilling:
    async def test_checkout_returns_manual_instructions(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/billing/checkout",
            headers=org_headers(org_and_tokens),
            json={"plan_key": "pro"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["provider"] == "manual"
        assert body["url"] is None
        assert "₱1,999.00" in (body["manual_instructions"] or "")

    async def test_confirm_records_invoice(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "pro"})
        invoices = (await client.get("/v1/billing/invoices", headers=headers)).json()
        assert any(i["total_cents"] == 199900 and i["currency"] == "PHP" for i in invoices)

    async def test_custom_priced_plan_not_publicly_listed(self, client: AsyncClient, org_and_tokens) -> None:
        plans = (
            await client.get(
                "/v1/plans", headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"}
            )
        ).json()
        keys = [p["key"] for p in plans]
        assert "enterprise" not in keys
        assert "free" in keys

    async def test_unknown_plan_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/billing/checkout",
            headers=org_headers(org_and_tokens),
            json={"plan_key": "diamond"},
        )
        assert res.status_code == 404


class TestRoleManagement:
    async def test_custom_role_crud(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)

        created = await client.post(
            "/v1/roles",
            headers=headers,
            json={"key": "viewer", "name": "Viewer", "permissions": ["project:read"]},
        )
        assert created.status_code == 201, created.text
        role_id = created.json()["id"]

        listed = (await client.get("/v1/roles", headers=headers)).json()
        assert any(r["key"] == "viewer" for r in listed)

        updated = await client.patch(
            f"/v1/roles/{role_id}",
            headers=headers,
            json={"name": "Read-only Viewer"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Read-only Viewer"

        deleted = await client.delete(f"/v1/roles/{role_id}", headers=headers)
        assert deleted.status_code == 204

    async def test_unknown_permission_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/roles",
            headers=org_headers(org_and_tokens),
            json={"key": "bad", "name": "Bad", "permissions": ["nope:nada"]},
        )
        assert res.status_code == 403

    async def test_system_roles_visible_immutable(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        roles = (await client.get("/v1/roles", headers=headers)).json()
        system = next(r for r in roles if r["key"] == "owner")
        res = await client.delete(f"/v1/roles/{system['id']}", headers=headers)
        assert res.status_code == 404  # cross-org scope: system roles aren't org-scoped


class TestPermissionDenied:
    async def test_member_cannot_manage_billing(
        self, client: AsyncClient, org_and_tokens, db_session
    ) -> None:
        """A plain member (no billing:manage) is 403 on plan change."""
        from synapse_saas.tenancy.service import OrganizationService

        headers = org_headers(org_and_tokens)
        invited = await client.post(
            "/v1/orgs/current/members/invite",
            headers=headers,
            json={"email": "plainmember@x.example"},
        )
        assert invited.status_code == 201

        reg = await client.post(
            "/v1/auth/register",
            json={
                "email": "plainmember@x.example",
                "password": "password12345",
                "display_name": "Plain",
            },
        )
        member_token = reg.json()["tokens"]["access_token"]

        # Accept the invite out-of-band (the service path the email link drives)
        org_id = uuid.UUID(org_and_tokens["org_id"])
        from synapse_saas.core.db import get_session_factory

        factory = get_session_factory()
        async with factory() as accept_session:
            await OrganizationService(accept_session).accept_invite_by_email(org_id, "plainmember@x.example")
            await accept_session.commit()

        res = await client.post(
            "/v1/subscription/change",
            headers={
                "Authorization": f"Bearer {member_token}",
                "X-Org-Id": org_and_tokens["org_id"],
            },
            json={"plan_key": "pro"},
        )
        assert res.status_code == 403
        assert res.json()["type"].endswith("/permission_denied")
