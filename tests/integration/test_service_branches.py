"""Branch coverage: suspend/unsuspend, owner guards, checkout webhooks, expiry."""

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


@pytest.fixture(autouse=True)
async def _fresh_engine(clean_db):
    from synapse_saas.core.db import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


async def _make_platform_admin(email: str) -> None:
    from sqlalchemy import select

    from synapse_saas.core.db import get_session_factory
    from synapse_saas.identity.models import User

    factory = get_session_factory()
    async with factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.is_platform_admin = True
        await session.commit()


class TestPlatformAdminSurface:
    async def test_suspend_then_unsuspend(self, client: AsyncClient, org_and_tokens) -> None:
        await _make_platform_admin("owner@example.com")
        token = org_and_tokens["access_token"]
        org_id = org_and_tokens["org_id"]

        suspended = await client.post(
            f"/v1/orgs/{org_id}/suspend", headers={"Authorization": f"Bearer {token}"}
        )
        assert suspended.status_code == 204

        org = (await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))).json()
        assert org["status"] == "suspended"

        unsuspended = await client.delete(
            f"/v1/orgs/{org_id}/suspend", headers={"Authorization": f"Bearer {token}"}
        )
        assert unsuspended.status_code == 204
        org = (await client.get("/v1/orgs/current", headers=org_headers(org_and_tokens))).json()
        assert org["status"] == "active"

    async def test_non_admin_cannot_suspend(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            f"/v1/orgs/{org_and_tokens['org_id']}/suspend",
            headers={"Authorization": f"Bearer {org_and_tokens['access_token']}"},
        )
        assert res.status_code == 404


class TestOwnerGuards:
    async def test_owner_membership_cannot_be_removed(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        members = (await client.get("/v1/orgs/current/members", headers=headers)).json()["data"]
        owner_membership = members[0]["id"]

        res = await client.delete(f"/v1/memberships/{owner_membership}", headers=headers)
        assert res.status_code == 404  # NotAMemberError → owner protected

    async def test_remove_nonexistent_membership(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.delete(f"/v1/memberships/{uuid.uuid4()}", headers=org_headers(org_and_tokens))
        assert res.status_code == 404

    async def test_update_nonexistent_membership(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.patch(
            f"/v1/memberships/{uuid.uuid4()}",
            headers=org_headers(org_and_tokens),
            json={"status": "suspended"},
        )
        assert res.status_code == 404


class TestCheckoutCompletedWebhook:
    async def test_checkout_activates_plan(self, client: AsyncClient, org_and_tokens) -> None:
        """checkout.session.completed carries plan_key metadata → subscription."""
        import hashlib
        import hmac
        import json
        import time

        from synapse_saas.core.config import get_settings

        headers = org_headers(org_and_tokens)
        # Seed the billing customer so org lookup resolves
        await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "free"})
        from sqlalchemy import select

        from synapse_saas.billing.models import BillingCustomer
        from synapse_saas.core.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            customer = (
                await session.execute(
                    select(BillingCustomer).where(
                        BillingCustomer.organization_id == uuid.UUID(org_and_tokens["org_id"])
                    )
                )
            ).scalar_one()

        secret = "whsec_checkout"
        import os

        os.environ["SYNAPSE_STRIPE_WEBHOOK_SECRET"] = secret
        os.environ["SYNAPSE_STRIPE_SECRET_KEY"] = "sk_test_x"
        get_settings.cache_clear()

        event = {
            "id": "evt_co_1",
            "type": "checkout.session.completed",
            "created": int(time.time()),
            "data": {
                "object": {
                    "id": "cs_1",
                    "object": "checkout_session",
                    "customer": customer.provider_customer_id,
                    "metadata": {"plan_key": "pro"},
                }
            },
        }
        body = json.dumps(event).encode()
        ts = int(time.time())
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()

        res = await client.post(
            "/v1/billing/webhooks/stripe",
            headers={"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"},
            content=body,
        )
        assert res.status_code == 200, res.text
        assert res.json()["events_applied"] == 1

        sub = (await client.get("/v1/subscription", headers=headers)).json()["subscription"]
        assert sub["plan_snapshot"]["key"] == "pro"
        get_settings.cache_clear()

    async def test_unknown_provider_path(self, client: AsyncClient) -> None:
        res = await client.post("/v1/billing/webhooks/alipay", json={})
        assert res.status_code == 404


class TestEntitlementExpiryJobPath:
    async def test_worker_expiry_matches_service_revocation(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        grant = await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={"feature_key": "sso", "source": "beta", "duration_days": 7},
        )
        assert grant.status_code == 201

        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert "sso" in ent["features"]

        from sqlalchemy import text

        from synapse_saas.core.cache import VersionedCache
        from synapse_saas.core.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            # Backdate, run job, then revoke through the service path
            await session.execute(text("UPDATE entitlements SET ends_at = now() - interval '1 second'"))
            await session.commit()

        from synapse_saas.worker.jobs import expire_entitlements

        assert await expire_entitlements({}) == 1
        await VersionedCache("entl").bump(org_and_tokens["org_id"])

        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert "sso" not in ent["features"]
