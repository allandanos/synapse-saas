"""Usage metering contract fixes (P2 / WS-B):

- `/usage/consume` with >1 event is a 422 (it used to silently drop the rest)
- `/usage/consume-batch` is all-or-nothing
- `idempotency_key` really dedupes — including two concurrent retries
- gauges are levels set through `/usage/gauge`, never counted through events
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.integration.conftest import grant_as_platform

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


async def _used(client: AsyncClient, fixture: dict[str, str], metric: str) -> int:
    res = await client.get("/v1/usage/check", headers=org_headers(fixture), params={"metric": metric})
    assert res.status_code == 200, res.text
    return int(res.json()["used"])


class TestConsumeShape:
    async def test_consume_two_events_422(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/usage/consume",
            headers=org_headers(org_and_tokens),
            json={
                "events": [
                    {"metric": "api_requests", "quantity": 1},
                    {"metric": "api_requests", "quantity": 1},
                ]
            },
        )
        assert res.status_code == 422, res.text
        assert res.json()["batch_url"] == "/v1/usage/consume-batch"
        assert await _used(client, org_and_tokens, "api_requests") == 0  # nothing was counted

    async def test_consume_batch_counts_every_event(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.post(
            "/v1/usage/consume-batch",
            headers=org_headers(org_and_tokens),
            json={
                "events": [
                    {"metric": "api_requests", "quantity": 3},
                    {"metric": "api_requests", "quantity": 4},
                ]
            },
        )
        assert res.status_code == 200, res.text
        assert [r["total"] for r in res.json()] == [3, 7]
        assert await _used(client, org_and_tokens, "api_requests") == 7

    async def test_consume_batch_atomic_rollback_on_breach(self, client: AsyncClient, org_and_tokens) -> None:
        """Free plan: api_requests = 10,000. The 3rd event breaches ⇒ none of the batch counts."""
        res = await client.post(
            "/v1/usage/consume-batch",
            headers=org_headers(org_and_tokens),
            json={
                "events": [
                    {"metric": "api_requests", "quantity": 4000},
                    {"metric": "api_requests", "quantity": 4000},
                    {"metric": "api_requests", "quantity": 4000},
                ]
            },
        )
        assert res.status_code == 402, res.text
        assert res.json()["metric"] == "api_requests"
        assert await _used(client, org_and_tokens, "api_requests") == 0


class TestIdempotency:
    async def test_retry_with_same_key_is_not_counted_twice(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        body = {"events": [{"metric": "api_requests", "quantity": 7, "idempotency_key": "req-1"}]}
        first = (await client.post("/v1/usage/events", headers=headers, json=body)).json()[0]
        second = (await client.post("/v1/usage/events", headers=headers, json=body)).json()[0]
        assert first == {**first, "total": 7, "deduplicated": False}
        assert second["deduplicated"] is True and second["total"] == 7 and second["quantity"] == 7
        assert await _used(client, org_and_tokens, "api_requests") == 7

    async def test_consume_replay_returns_the_original_result(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        body = {"events": [{"metric": "api_requests", "quantity": 5, "idempotency_key": "c-1"}]}
        first = (await client.post("/v1/usage/consume", headers=headers, json=body)).json()
        replay = (await client.post("/v1/usage/consume", headers=headers, json=body)).json()
        assert replay["deduplicated"] is True
        assert replay["total"] == first["total"] == 5
        assert replay["limit"] == 10000 and replay["within_limit"] is True

    async def test_idempotency_key_dedupes_concurrent_retries(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        body = {"events": [{"metric": "api_requests", "quantity": 9, "idempotency_key": "race-1"}]}
        responses = await asyncio.gather(
            *(client.post("/v1/usage/events", headers=headers, json=body) for _ in range(4))
        )
        assert {r.status_code for r in responses} == {201}
        flags = sorted(r.json()[0]["deduplicated"] for r in responses)
        assert flags == [False, True, True, True]
        assert await _used(client, org_and_tokens, "api_requests") == 9

    async def test_breached_consume_does_not_burn_the_key(self, client: AsyncClient, org_and_tokens) -> None:
        """A 402 rolls the reservation back; raising the limit lets the same key succeed."""
        headers = org_headers(org_and_tokens)
        body = {"events": [{"metric": "api_requests", "quantity": 20000, "idempotency_key": "big-1"}]}
        assert (await client.post("/v1/usage/consume", headers=headers, json=body)).status_code == 402
        await grant_as_platform(
            client,
            org_and_tokens["org_id"],
            {"feature_key": "limit:api_requests", "source": "addon", "limit_value": 50000},
        )
        res = await client.post("/v1/usage/consume", headers=headers, json=body)
        assert res.status_code == 200, res.text
        assert res.json()["deduplicated"] is False and res.json()["total"] == 20000

    async def test_keys_are_per_org(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        other = await client.post(
            "/v1/orgs",
            headers={"Authorization": headers["Authorization"]},
            json={"name": "Other", "slug": "other-org"},
        )
        other_headers = {**headers, "X-Org-Id": other.json()["id"]}
        body = {"events": [{"metric": "api_requests", "quantity": 2, "idempotency_key": "shared-key"}]}
        a = (await client.post("/v1/usage/events", headers=headers, json=body)).json()[0]
        b = (await client.post("/v1/usage/events", headers=other_headers, json=body)).json()[0]
        assert a["deduplicated"] is False and b["deduplicated"] is False


class TestGauges:
    async def test_set_and_adjust_a_gauge(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        res = await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "value": 2})
        assert res.status_code == 200, res.text
        assert res.json() == {**res.json(), "total": 2, "limit": 2, "remaining": 0, "within_limit": True}
        res = await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "delta": -1})
        assert res.json()["total"] == 1
        res = await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "delta": -5})
        assert res.json()["total"] == 0  # never below zero
        assert await _used(client, org_and_tokens, "projects") == 0

    async def test_positive_delta_is_capacity_checked(self, client: AsyncClient, org_and_tokens) -> None:
        """Free plan: projects = 2. The third one is a 402 and the level stays put."""
        headers = org_headers(org_and_tokens)
        for _ in range(2):
            assert (
                await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "delta": 1})
            ).status_code == 200
        res = await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "delta": 1})
        assert res.status_code == 402, res.text
        assert res.json()["metric"] == "projects" and res.json()["limit"] == 2
        assert await _used(client, org_and_tokens, "projects") == 2
        # `value` is a sync, not a request for capacity: it is never refused
        res = await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "value": 5})
        assert res.status_code == 200 and res.json()["within_limit"] is False

    async def test_gauge_survives_the_period(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects", "value": 2})
        summary = (
            await client.get("/v1/usage/summary", headers=headers, params={"period": "2001-01"})
        ).json()
        by_metric = {m["metric"]: m for m in summary["metrics"]}
        assert by_metric["projects"]["used"] == 2  # a level, not a per-month flow

    async def test_counters_reject_gauge_metrics(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        for path in ("/v1/usage/events", "/v1/usage/consume"):
            res = await client.post(
                path, headers=headers, json={"events": [{"metric": "projects", "quantity": 1}]}
            )
            assert res.status_code == 422, (path, res.text)
            assert res.json()["kind"] == "gauge"

    async def test_gauge_route_rejects_counters_and_bad_bodies(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        res = await client.post(
            "/v1/usage/gauge", headers=headers, json={"metric": "api_requests", "value": 1}
        )
        assert res.status_code == 422 and res.json()["kind"] == "counter"
        res = await client.post("/v1/usage/gauge", headers=headers, json={"metric": "projects"})
        assert res.status_code == 422
        res = await client.post(
            "/v1/usage/gauge", headers=headers, json={"metric": "projects", "value": 1, "delta": 1}
        )
        assert res.status_code == 422

    async def test_seat_gauge_follows_memberships(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        assert await _used(client, org_and_tokens, "users") == 1  # the owner
        inv = await client.post(
            "/v1/orgs/current/members/invite", headers=headers, json={"email": "a@example.com"}
        )
        assert inv.status_code == 201, inv.text
        assert await _used(client, org_and_tokens, "users") == 2  # pending invites hold a seat
        res = await client.delete(f"/v1/memberships/{inv.json()['id']}", headers=headers)
        assert res.status_code == 204, res.text
        assert await _used(client, org_and_tokens, "users") == 1
