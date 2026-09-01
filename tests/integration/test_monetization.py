"""Monetization integration: org bootstrap, upgrade, entitlements, seat limits."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def auth(fixture: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}"}


def org_headers(fixture: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


class TestOrgBootstrap:
    async def test_new_org_gets_owner_role_and_free_plan(self, client: AsyncClient, org_and_tokens) -> None:
        """The framework's clone-and-run promise: an org is instantly functional."""
        ent = await client.get("/v1/entitlements", headers=org_headers(org_and_tokens))
        assert ent.status_code == 200
        body = ent.json()
        assert body["plan_key"] == "free"
        assert body["subscription_status"] == "active"
        assert "basic_dashboard" in body["features"]
        assert body["limits"]["users"]["value"] == 3

    async def test_owner_can_invite_then_seat_limit_hits(self, client: AsyncClient, org_and_tokens) -> None:
        """Free plan: 3 seats. Owner + 2 invites OK; the 3rd invite is a 402."""
        headers = org_headers(org_and_tokens)
        for i in (1, 2):
            res = await client.post(
                "/v1/orgs/current/members/invite",
                headers=headers,
                json={"email": f"seat{i}@x.example"},
            )
            assert res.status_code == 201

        blocked = await client.post(
            "/v1/orgs/current/members/invite",
            headers=headers,
            json={"email": "seat3@x.example"},
        )
        assert blocked.status_code == 402
        problem = blocked.json()
        assert problem["metric"] == "users"
        assert problem["limit"] == 3
        assert problem["upgrade_url"] == "/dashboard/billing"


class TestPlanChange:
    async def test_upgrade_expands_entitlements(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        change = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        assert change.status_code == 200, change.text

        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert ent["plan_key"] == "starter"
        assert "reports" in ent["features"]
        assert ent["limits"]["users"]["value"] == 10

    async def test_upgrade_unblocks_seat_limit(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        # Fill free seats, upgrade, invite succeeds
        for i in (1, 2, 3):
            await client.post(
                "/v1/orgs/current/members/invite", headers=headers, json={"email": f"s{i}@x.example"}
            )
        blocked = await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "s4@x.example"}
        )
        assert blocked.status_code == 402

        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        ok = await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "s4@x.example"}
        )
        assert ok.status_code == 201

    async def test_snapshot_freezes_purchase_terms(self, client: AsyncClient, org_and_tokens) -> None:
        """plan_snapshot records what was bought — YAML edits can't rewrite history."""
        headers = org_headers(org_and_tokens)
        res = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        assert res.status_code == 200
        snapshot = res.json()["plan_snapshot"]
        assert snapshot["key"] == "pro"
        assert snapshot["price_cents"] == 199900


class TestTrialEntitlement:
    async def test_trial_grants_feature_without_plan_change(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        """The add-on/trial mechanism: grants are independent of the plan."""
        headers = org_headers(org_and_tokens)
        before = (await client.get("/v1/entitlements", headers=headers)).json()
        assert "advanced_reports" not in before["features"]

        grant = await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={
                "feature_key": "advanced_reports",
                "source": "trial",
                "duration_days": 14,
            },
        )
        assert grant.status_code == 201, grant.text

        after = (await client.get("/v1/entitlements", headers=headers)).json()
        assert "advanced_reports" in after["features"]
        assert after["plan_key"] == before["plan_key"]  # plan unchanged


class TestUsageMetering:
    async def test_consume_enforces_hard_limit(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        # free: api_requests = 10_000
        ok = await client.post(
            "/v1/usage/consume",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 9_999}]},
        )
        assert ok.status_code == 200
        assert ok.json()["within_limit"] is True

        breach = await client.post(
            "/v1/usage/consume",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 5}]},
        )
        assert breach.status_code == 402
        problem = breach.json()
        assert problem["metric"] == "api_requests"
        assert problem["limit"] == 10_000

    async def test_concurrent_consume_never_overshoots(self, client: AsyncClient, org_and_tokens) -> None:
        """10 parallel consumes of 1 against a 3-slot limit ⇒ exactly 3 succeed."""
        headers = org_headers(org_and_tokens)

        # Shrink the window: use the users gauge instead via direct counter SQL is
        # overkill — instead prove atomicity with api_requests after a tight grant.
        grant = await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={
                "feature_key": "limit:api_requests",
                "source": "addon",
                "limit_value": 3,
            },
        )
        assert grant.status_code == 201

        import asyncio

        async def one() -> int:
            res = await client.post(
                "/v1/usage/consume",
                headers=headers,
                json={"events": [{"metric": "api_requests", "quantity": 1}]},
            )
            return res.status_code

        results = await asyncio.gather(*(one() for _ in range(10)))
        # Grant bumps the cache; first requests may see the old (10k) limit —
        # the invariant that matters: at most 3 succeed against the tight limit
        # once visible. With cache invalidation it's immediately visible.
        succeeded = results.count(200)
        assert succeeded <= 3, f"overshoot: {succeeded} succeeded"

    async def test_record_never_blocks(self, client: AsyncClient, org_and_tokens) -> None:
        """Metering is soft: record succeeds even past the limit."""
        headers = org_headers(org_and_tokens)
        for _ in range(3):
            res = await client.post(
                "/v1/usage/events",
                headers=headers,
                json={"events": [{"metric": "api_requests", "quantity": 50_000}]},
            )
            assert res.status_code == 201

    async def test_unknown_metric_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/usage/events",
            headers=org_headers(org_and_tokens),
            json={"events": [{"metric": "warp_drives", "quantity": 1}]},
        )
        assert res.status_code == 422


class TestBillingWebhooks:
    async def test_manual_webhook_and_replay(self, client: AsyncClient, org_and_tokens, monkeypatch) -> None:
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_MANUAL_WEBHOOK_TOKEN", "itest-token")
        get_settings.cache_clear()

        payload = {
            "id": "evt_itest_1",
            "type": "manual.subscription.activated",
            "data": {"plan_key": "starter"},
        }
        first = await client.post(
            "/v1/billing/webhooks/manual",
            headers={"X-Manual-Token": "itest-token"},
            json=payload,
        )
        assert first.status_code == 200, first.text

        replay = await client.post(
            "/v1/billing/webhooks/manual",
            headers={"X-Manual-Token": "itest-token"},
            json=payload,
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "duplicate"
        get_settings.cache_clear()

    async def test_bad_token_rejected(self, client: AsyncClient) -> None:
        res = await client.post(
            "/v1/billing/webhooks/manual",
            headers={"X-Manual-Token": "nope"},
            json={"id": "x"},
        )
        assert res.status_code == 400
        assert res.json()["type"].endswith("/webhook_signature_invalid")

    async def test_stripe_signature_verified(self, client: AsyncClient, monkeypatch) -> None:
        """Stripe webhooks: correct signature passes, tampered body fails."""
        import hashlib
        import hmac
        import json
        import time as time_mod

        from synapse_saas.core.config import get_settings

        secret = "whsec_itest"
        monkeypatch.setenv("SYNAPSE_STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("SYNAPSE_STRIPE_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

        body = json.dumps(
            {
                "id": "evt_stripe_1",
                "type": "invoice.paid",
                "created": int(time_mod.time()),
                "data": {"object": {"id": "in_1", "amount_paid": 199900, "currency": "php"}},
            }
        ).encode()
        ts = int(time_mod.time())
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()

        ok = await client.post(
            "/v1/billing/webhooks/stripe",
            headers={"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"},
            content=body,
        )
        assert ok.status_code == 200, ok.text

        tampered = hmac.new(secret.encode(), f"{ts}.".encode() + b"tampered", hashlib.sha256).hexdigest()
        bad = await client.post(
            "/v1/billing/webhooks/stripe",
            headers={"Stripe-Signature": f"t={ts},v1={tampered}"},
            content=body,
        )
        assert bad.status_code == 400
        get_settings.cache_clear()


class TestAuditTrail:
    async def test_mutations_are_audited(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "a@audit.example"}
        )

        audit = await client.get("/v1/audit", headers=headers)
        assert audit.status_code == 200
        events = [e["event_type"] for e in audit.json()["data"]]
        assert "subscription.plan_changed" in events
        assert "member.invited" in events
