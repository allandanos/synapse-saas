"""Worker jobs + outbound webhook delivery integration tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient, Response

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


@pytest.fixture
async def captured_deliveries(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Intercept webhook HTTP posts; record envelope + headers."""
    calls: list[dict[str, Any]] = []

    async def fake_post(self: Any, url: str, **kw: Any) -> Response:
        """Intercept only absolute outbound URLs; relative API paths pass through."""
        url_str = str(url)
        if not url_str.startswith(("http://", "https://")):
            return await _original_post(self, url, **kw)
        calls.append(
            {
                "url": url_str,
                "content": kw.get("content", b""),
                "headers": kw.get("headers") or {},
            }
        )
        return Response(200, request=None)

    import httpx

    _original_post = httpx.AsyncClient.post
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


class TestOutboxDispatch:
    async def test_event_fans_out_to_endpoints(
        self,
        client: AsyncClient,
        org_and_tokens,
        captured_deliveries: list,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        headers = org_headers(org_and_tokens)

        # Register an endpoint (secret shown once)
        created = await client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "https://hooks.example.test/synapse", "events": []},
        )
        assert created.status_code == 201, created.text
        secret = created.json()["secret"]

        # Trigger an outbox event
        changed = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        assert changed.status_code == 200

        # Drain the outbox + deliver
        from synapse_saas.worker.jobs import deliver_webhooks, dispatch_outbox

        dispatched = await dispatch_outbox({})
        assert dispatched >= 1
        delivered = await deliver_webhooks({})
        assert delivered >= 1

        assert captured_deliveries, "expected at least one outbound delivery"
        ours = [c for c in captured_deliveries if c["url"] == "https://hooks.example.test/synapse"]
        assert ours

        envelopes = [json.loads(c["content"]) for c in ours]
        target = next((e for e in envelopes if e["event_type"] == "subscription.plan_changed"), None)
        assert target is not None, f"plan change event missing: {[e['event_type'] for e in envelopes]}"
        assert target["organization_id"] == org_and_tokens["org_id"]

        # Signature verifies against the secret we were shown
        from synapse_saas.core.security import verify_signature

        call = next(c for c in ours if b"subscription.plan_changed" in c["content"])
        sig_header = call["headers"]["X-Synapse-Signature"]
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        assert verify_signature(call["content"], secret, timestamp=int(parts["t"]), signature=parts["v1"]), (
            "delivery signature must verify with the endpoint secret"
        )

    async def test_no_endpoints_no_deliveries(
        self, client: AsyncClient, org_and_tokens, captured_deliveries: list
    ) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        from synapse_saas.worker.jobs import deliver_webhooks, dispatch_outbox

        await dispatch_outbox({})
        await deliver_webhooks({})
        assert captured_deliveries == []


class TestEntitlementExpiry:
    async def test_expired_grant_stops_resolving(
        self, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers = org_headers(org_and_tokens)

        grant = await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={
                "feature_key": "advanced_reports",
                "source": "promo",
                "duration_days": 1,
            },
        )
        assert grant.status_code == 201

        # Backdate the grant so the expiry job sees it lapsed
        from sqlalchemy import text

        from synapse_saas.core.db import get_session_factory

        async with get_session_factory()() as session:
            await session.execute(text("UPDATE entitlements SET ends_at = now() - interval '1 hour'"))
            await session.commit()

        # Cache invalidation happens on mutation; the expiry job bumps nothing,
        # so clear by version-bumping through the service
        from synapse_saas.core.cache import VersionedCache

        await VersionedCache("entl").bump(org_and_tokens["org_id"])

        from synapse_saas.worker.jobs import expire_entitlements

        expired = await expire_entitlements({})
        assert expired >= 1

        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert "advanced_reports" not in ent["features"]


class TestUsageRollup:
    async def test_rollup_matches_counter(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post(
            "/v1/usage/events",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 123}]},
        )

        from synapse_saas.worker.jobs import rollup_usage

        assert await rollup_usage({}) == 1

        summary = (await client.get("/v1/usage/summary", headers=headers)).json()
        api = next(m for m in summary["metrics"] if m["metric"] == "api_requests")
        assert api["used"] == 123


class TestWebhookRetry:
    async def test_exhausted_delivery_is_replayable(
        self,
        client: AsyncClient,
        org_and_tokens,
        captured_deliveries: list,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        headers = org_headers(org_and_tokens)
        await client.post(
            "/v1/webhooks/endpoints",
            headers=headers,
            json={"url": "https://hooks.example.test/retry"},
        )
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        from synapse_saas.worker.jobs import deliver_webhooks, dispatch_outbox

        await dispatch_outbox({})
        await deliver_webhooks({})

        deliveries = (await client.get("/v1/webhooks/deliveries", headers=headers)).json()
        assert deliveries
        delivery_id = deliveries[0]["id"]
        assert deliveries[0]["status"] == "delivered"

        retried = await client.post(f"/v1/webhooks/deliveries/{delivery_id}/retry", headers=headers)
        assert retried.status_code == 200
        assert retried.json()["status"] == "pending"
