"""Outbox dispatch semantics (P3 / WS-D):

- internal events (invite tokens, reset links, invoice mail) NEVER fan out
- endpoints only receive the event types they subscribed to
- one poison event cannot block the batch; it retries with backoff and is
  dead-lettered after OUTBOX_MAX_ATTEMPTS
- emails are sent only after the dispatch commit
- two workers never deliver the same webhook twice
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from tests.integration.conftest import owner_session_factory

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


async def _endpoint(client: AsyncClient, fixture: dict[str, str], url: str, events: list[str]) -> str:
    res = await client.post(
        "/v1/webhooks/endpoints", headers=org_headers(fixture), json={"url": url, "events": events}
    )
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


async def _deliveries(org_id: str) -> list[dict[str, Any]]:
    async with owner_session_factory()() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT event_type, payload::text AS payload, endpoint_id::text AS endpoint_id "
                    "FROM webhook_deliveries WHERE organization_id = :org ORDER BY created_at"
                ),
                {"org": org_id},
            )
        ).all()
        return [dict(r._mapping) for r in rows]


async def _outbox(org_id: str) -> list[dict[str, Any]]:
    async with owner_session_factory()() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id::text AS id, event_type, audience, published_at, attempts, dead_at, "
                    "next_attempt_at, last_error FROM outbox_events WHERE organization_id = :org ORDER BY id"
                ),
                {"org": org_id},
            )
        ).all()
        return [dict(r._mapping) for r in rows]


class TestAudience:
    async def test_invite_token_never_reaches_a_webhook_delivery(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        await _endpoint(client, org_and_tokens, "https://hooks.example.test/all", [])
        inv = await client.post(
            "/v1/orgs/current/members/invite",
            headers=org_headers(org_and_tokens),
            json={"email": "new@example.com"},
        )
        assert inv.status_code == 201, inv.text

        from synapse_saas.worker.jobs import dispatch_outbox

        await dispatch_outbox({})

        rows = await _outbox(org_and_tokens["org_id"])
        by_type = {r["event_type"]: r for r in rows}
        assert by_type["member.invited"]["audience"] == "public"
        assert by_type["member.invite_email"]["audience"] == "internal"
        assert by_type["member.invite_email"]["published_at"] is not None  # consumed, not fanned out

        deliveries = await _deliveries(org_and_tokens["org_id"])
        types = [d["event_type"] for d in deliveries]
        assert "member.invited" in types and "member.invite_email" not in types
        for d in deliveries:
            assert "invite_token" not in d["payload"], d
        public = next(d for d in deliveries if d["event_type"] == "member.invited")
        assert json.loads(public["payload"]) == {
            **json.loads(public["payload"]),
            "email": "new@example.com",
            "membership_id": inv.json()["id"],
        }

    async def test_events_filter_is_respected(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        plan_only = await _endpoint(
            client, org_and_tokens, "https://hooks.example.test/plans", ["subscription.plan_changed"]
        )
        everything = await _endpoint(client, org_and_tokens, "https://hooks.example.test/all", [])
        await client.post("/v1/orgs/current/members/invite", headers=headers, json={"email": "f@example.com"})
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})

        from synapse_saas.worker.jobs import dispatch_outbox

        await dispatch_outbox({})
        deliveries = await _deliveries(org_and_tokens["org_id"])
        for_plan_only = {d["event_type"] for d in deliveries if d["endpoint_id"] == plan_only}
        for_everything = {d["event_type"] for d in deliveries if d["endpoint_id"] == everything}
        assert for_plan_only == {"subscription.plan_changed"}
        assert {"member.invited", "subscription.plan_changed"} <= for_everything


class TestRetryAndDeadLetter:
    @pytest.fixture
    def poison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make fan-out fail for member.invited events only."""
        from synapse_saas.webhooks.models import WebhookDelivery

        original = WebhookDelivery.__init__

        def failing_init(self: Any, **kw: Any) -> None:
            if kw.get("event_type") == "member.invited":
                raise RuntimeError("simulated fan-out failure")
            original(self, **kw)

        monkeypatch.setattr(WebhookDelivery, "__init__", failing_init)

    async def test_bad_event_does_not_block_the_batch_and_retries_with_backoff(
        self, client: AsyncClient, org_and_tokens, poison: None
    ) -> None:
        headers = org_headers(org_and_tokens)
        await _endpoint(client, org_and_tokens, "https://hooks.example.test/all", [])
        await client.post("/v1/orgs/current/members/invite", headers=headers, json={"email": "p@example.com"})
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})

        from synapse_saas.worker.jobs import dispatch_outbox

        dispatched = await dispatch_outbox({})
        rows = {r["event_type"]: r for r in await _outbox(org_and_tokens["org_id"])}
        assert rows["subscription.plan_changed"]["published_at"] is not None  # the batch went through
        bad = rows["member.invited"]
        assert bad["published_at"] is None and bad["dead_at"] is None
        assert bad["attempts"] == 1 and "simulated fan-out failure" in bad["last_error"]
        assert dispatched == len([r for r in rows.values() if r["published_at"] is not None])
        # backoff: not due again yet ⇒ a second tick does not touch it
        assert (await dispatch_outbox({})) == 0
        assert {r["event_type"]: r["attempts"] for r in await _outbox(org_and_tokens["org_id"])}[
            "member.invited"
        ] == 1

    async def test_dead_letter_after_max_attempts(
        self, client: AsyncClient, org_and_tokens, poison: None
    ) -> None:
        headers = org_headers(org_and_tokens)
        await _endpoint(client, org_and_tokens, "https://hooks.example.test/all", [])
        await client.post("/v1/orgs/current/members/invite", headers=headers, json={"email": "d@example.com"})

        from synapse_saas.worker.jobs import OUTBOX_MAX_ATTEMPTS, dispatch_outbox

        await dispatch_outbox({})
        async with owner_session_factory()() as session:
            await session.execute(
                text(
                    "UPDATE outbox_events SET attempts = :n, next_attempt_at = now() "
                    "WHERE organization_id = :org AND event_type = 'member.invited'"
                ),
                {"n": OUTBOX_MAX_ATTEMPTS - 1, "org": org_and_tokens["org_id"]},
            )
            await session.commit()

        await dispatch_outbox({})
        bad = next(r for r in await _outbox(org_and_tokens["org_id"]) if r["event_type"] == "member.invited")
        assert bad["dead_at"] is not None and bad["attempts"] == OUTBOX_MAX_ATTEMPTS
        assert bad["published_at"] is None
        # Dead-lettered ⇒ out of the loop for good
        async with owner_session_factory()() as session:
            await session.execute(
                text("UPDATE outbox_events SET next_attempt_at = now() WHERE organization_id = :org"),
                {"org": org_and_tokens["org_id"]},
            )
            await session.commit()
        assert (await dispatch_outbox({})) == 0


class TestEmailAfterCommit:
    async def test_email_handler_runs_only_after_the_events_are_published(
        self, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/orgs/current/members/invite", headers=headers, json={"email": "m@example.com"})

        seen: list[tuple[str, bool]] = []
        from synapse_saas.notifications import handlers

        async def fake_handle(event_type: str, payload: dict[str, Any]) -> None:
            # Observed from a fresh session: is the event already durably published?
            async with owner_session_factory()() as session:
                published = (
                    await session.execute(
                        text(
                            "SELECT published_at IS NOT NULL FROM outbox_events "
                            "WHERE organization_id = :org AND event_type = :t"
                        ),
                        {"org": org_and_tokens["org_id"], "t": event_type},
                    )
                ).scalar_one()
            seen.append((event_type, bool(published)))

        monkeypatch.setattr(handlers, "handle_event", fake_handle)
        from synapse_saas.worker.jobs import dispatch_outbox

        await dispatch_outbox({})
        assert ("member.invite_email", True) in seen
        assert all(published for _, published in seen), seen


class TestConcurrentWorkers:
    async def test_two_workers_never_deliver_the_same_webhook_twice(
        self, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers = org_headers(org_and_tokens)
        await _endpoint(client, org_and_tokens, "https://hooks.example.test/once", [])
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})

        posts: list[str] = []
        import httpx

        original_post = httpx.AsyncClient.post

        async def fake_post(self: Any, url: str, **kw: Any) -> Response:
            if not str(url).startswith("http"):
                return await original_post(self, url, **kw)
            posts.append(str(url))
            await asyncio.sleep(0.2)  # hold the row lock long enough for the other worker to skip it
            return Response(200, request=None)

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        from synapse_saas.worker.jobs import deliver_webhooks, dispatch_outbox

        await dispatch_outbox({})
        pending = await _deliveries(org_and_tokens["org_id"])
        assert pending, "a delivery should be queued"

        delivered = await asyncio.gather(deliver_webhooks({}), deliver_webhooks({}))
        assert sum(delivered) == len(pending)
        assert len(posts) == len(pending), posts
