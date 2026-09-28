"""Worker jobs + outbound webhook delivery integration tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient, Response

from tests.integration.conftest import grant_as_platform, owner_session_factory

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

        grant = await grant_as_platform(
            client,
            org_and_tokens["org_id"],
            {
                "feature_key": "advanced_reports",
                "source": "promo",
                "duration_days": 1,
            },
        )
        assert grant.status_code == 201

        # Backdate the grant so the expiry job sees it lapsed
        from sqlalchemy import text

        async with owner_session_factory()() as session:
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


# ── H4: every provider WE bill renews; hosted providers renew themselves ──────


class TestRecurringBilling:
    async def _org_on_starter(self, client: AsyncClient, org_and_tokens, slug: str, provider: str) -> str:
        auth = {"Authorization": f"Bearer {org_and_tokens['access_token']}"}
        org = await client.post("/v1/orgs", headers=auth, json={"name": slug, "slug": slug})
        org_id = org.json()["id"]
        headers = {**auth, "X-Org-Id": org_id}
        res = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        assert res.status_code == 200, res.text
        from sqlalchemy import text

        async with owner_session_factory()() as session:
            await session.execute(
                text(
                    "UPDATE subscriptions SET provider = :provider, "
                    "current_period_start = now() - interval '31 days', "
                    "current_period_end = now() - interval '1 day' "
                    "WHERE organization_id = :org"
                ),
                {"provider": provider, "org": org_id},
            )
            await session.commit()
        return org_id

    async def test_advance_recurring_bills_xendit_and_manual_not_stripe(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        manual = await self._org_on_starter(client, org_and_tokens, "renew-manual", "manual")
        xendit = await self._org_on_starter(client, org_and_tokens, "renew-xendit", "xendit")
        stripe = await self._org_on_starter(client, org_and_tokens, "renew-stripe", "stripe")

        from synapse_saas.worker.jobs import advance_recurring_billing

        assert await advance_recurring_billing({}) == 2
        assert await advance_recurring_billing({}) == 0  # periods rolled: nothing due now

        from sqlalchemy import text

        async with owner_session_factory()() as session:
            invoices = (
                await session.execute(
                    text(
                        "SELECT organization_id::text AS org, number, status, total_cents "
                        "FROM invoices WHERE provider = 'synapse' ORDER BY organization_id"
                    )
                )
            ).all()
            periods = (
                await session.execute(
                    text(
                        "SELECT organization_id::text AS org, current_period_end > now() AS rolled "
                        "FROM subscriptions"
                    )
                )
            ).all()
        by_org = {row.org: row for row in invoices}
        assert set(by_org) == {manual, xendit}  # stripe renews on Stripe's side
        for org in (manual, xendit):
            assert by_org[org].status == "open" and by_org[org].number.startswith("INV-")
            assert by_org[org].total_cents == 49900  # the ended period, through the invoicing engine
        rolled = {row.org: row.rolled for row in periods}
        assert rolled[manual] and rolled[xendit] and not rolled[stripe]


# ── P3 / D8: partitions ahead + default, retention that keeps the audit trail ─


class TestPartitionsAndRetention:
    async def test_partitions_exist_three_months_ahead_plus_default(self, client: AsyncClient) -> None:
        from sqlalchemy import text

        from synapse_saas.worker.jobs import PARTITION_MONTHS_AHEAD, ensure_partitions

        assert await ensure_partitions({}) == PARTITION_MONTHS_AHEAD + 1
        async with owner_session_factory()() as session:
            names = set(
                (
                    await session.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'usage_events'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        for i in range(PARTITION_MONTHS_AHEAD + 1):
            month = (now.month - 1 + i) % 12 + 1
            year = now.year + (now.month - 1 + i) // 12
            assert f"usage_events_y{year}m{month:02d}" in names
        assert "usage_events_default" in names  # a lapsed cron degrades, it does not 500

    async def test_retention_keeps_exhausted_deliveries_and_honours_audit_setting(
        self, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sqlalchemy import text

        from synapse_saas.core.config import get_settings
        from synapse_saas.worker.jobs import purge_expired

        monkeypatch.setenv("SYNAPSE_AUDIT_RETENTION_DAYS", "10")
        get_settings.cache_clear()
        org = org_and_tokens["org_id"]
        async with owner_session_factory()() as session:
            endpoint_id = (
                await session.execute(
                    text(
                        "INSERT INTO webhook_endpoints "
                        "(id, organization_id, url, secret_encrypted, events, is_active) "
                        "VALUES (gen_random_uuid(), :org, 'https://x.test', 'enc', '{}', true) RETURNING id"
                    ),
                    {"org": org},
                )
            ).scalar_one()
            for status, age in (("delivered", 40), ("exhausted", 40), ("exhausted", 100)):
                await session.execute(
                    text(
                        "INSERT INTO webhook_deliveries "
                        "(id, endpoint_id, organization_id, event_type, payload, attempts, max_attempts, "
                        "next_attempt_at, status, created_at) VALUES "
                        "(gen_random_uuid(), :ep, :org, 'x.y', '{}', 5, 5, now(), :status, "
                        "now() - make_interval(days => :age))"
                    ),
                    {"ep": endpoint_id, "org": org, "status": status, "age": age},
                )
            await session.execute(
                text(
                    "INSERT INTO audit_logs (id, organization_id, actor_type, event_type, created_at) "
                    "VALUES (gen_random_uuid(), :org, 'system', 'old.event', now() - interval '30 days'), "
                    "(gen_random_uuid(), :org, 'system', 'fresh.event', now())"
                ),
                {"org": org},
            )
            await session.commit()

        await purge_expired({})
        get_settings.cache_clear()

        async with owner_session_factory()() as session:
            statuses = (
                (
                    await session.execute(
                        text(
                            "SELECT status FROM webhook_deliveries "
                            "WHERE organization_id = :org ORDER BY status"
                        ),
                        {"org": org},
                    )
                )
                .scalars()
                .all()
            )
            audit = (
                (
                    await session.execute(
                        text(
                            "SELECT event_type FROM audit_logs "
                            "WHERE organization_id = :org AND event_type LIKE '%.event'"
                        ),
                        {"org": org},
                    )
                )
                .scalars()
                .all()
            )
        assert statuses == [
            "exhausted"
        ]  # the 40-day exhausted row survives; delivered@40d and exhausted@100d go
        assert audit == ["fresh.event"]
