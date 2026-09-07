"""Agent registry integration: CRUD, entitlement gating, isolation, events,
AI-metering wiring (plan limits + token overage billing).

Phase 4 scope per ADR 0007: governance and commerce only. Nothing here
executes an agent — that is the agentic runtime's job.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


async def _upgrade_to_pro(client: AsyncClient, fixture: dict[str, str]) -> None:
    """Manual provider: checkout+confirm activates pro (agents entitled)."""
    headers = org_headers(fixture)
    checkout = await client.post("/v1/billing/checkout", headers=headers, json={"plan_key": "pro"})
    assert checkout.status_code == 200, checkout.text
    confirmed = await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "pro"})
    assert confirmed.status_code == 200, confirmed.text


async def _create_agent(client: AsyncClient, fixture: dict[str, str], slug: str = "support-bot") -> dict:
    res = await client.post(
        "/v1/agents",
        headers=org_headers(fixture),
        json={
            "slug": slug,
            "name": "Support Bot",
            "description": "Front-line triage",
            "config": {"model": "gpt-4o-mini", "tools": ["kb_search", "ticket_create"]},
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


class TestAgentGating:
    async def test_free_plan_is_403_with_upgrade_hints(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/agents", headers=org_headers(org_and_tokens))
        assert res.status_code == 403
        body = res.json()
        assert body["feature"] == "agents"  # extras merge at top level
        assert "pro" in body["available_in"]
        assert body["upgrade_url"] == "/dashboard/billing"

    async def test_pro_plan_unblocks_the_registry(self, client: AsyncClient, org_and_tokens) -> None:
        await _upgrade_to_pro(client, org_and_tokens)
        res = await client.get("/v1/agents", headers=org_headers(org_and_tokens))
        assert res.status_code == 200
        assert res.json() == []

    async def test_starter_still_gated(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/billing/checkout", headers=headers, json={"plan_key": "starter"})
        await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "starter"})
        res = await client.get("/v1/agents", headers=headers)
        assert res.status_code == 403


class TestAgentCrud:
    async def test_create_lists_updates_disables(self, client: AsyncClient, org_and_tokens) -> None:
        await _upgrade_to_pro(client, org_and_tokens)
        headers = org_headers(org_and_tokens)

        agent = await _create_agent(client, org_and_tokens)
        assert agent["status"] == "active"
        assert agent["config"]["model"] == "gpt-4o-mini"

        listed = (await client.get("/v1/agents", headers=headers)).json()
        assert [a["slug"] for a in listed] == ["support-bot"]

        patched = await client.patch(
            f"/v1/agents/{agent['id']}",
            headers=headers,
            json={"name": "Support Bot v2", "config": {"model": "claude-sonnet", "tools": ["kb_search"]}},
        )
        assert patched.status_code == 200
        assert patched.json()["name"] == "Support Bot v2"
        assert patched.json()["config"]["model"] == "claude-sonnet"

        disabled = await client.post(f"/v1/agents/{agent['id']}/disable", headers=headers)
        assert disabled.json()["status"] == "disabled"
        re_enabled = await client.post(f"/v1/agents/{agent['id']}/enable", headers=headers)
        assert re_enabled.json()["status"] == "active"

    async def test_duplicate_slug_conflicts(self, client: AsyncClient, org_and_tokens) -> None:
        await _upgrade_to_pro(client, org_and_tokens)
        await _create_agent(client, org_and_tokens)
        dup = await client.post(
            "/v1/agents",
            headers=org_headers(org_and_tokens),
            json={"slug": "support-bot", "name": "Impostor"},
        )
        assert dup.status_code == 409

    async def test_delete_is_soft_and_revives_slug_conflict(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        await _upgrade_to_pro(client, org_and_tokens)
        headers = org_headers(org_and_tokens)
        agent = await _create_agent(client, org_and_tokens)

        gone = await client.delete(f"/v1/agents/{agent['id']}", headers=headers)
        assert gone.status_code == 204
        assert (await client.get("/v1/agents", headers=headers)).json() == []
        # soft-deleted rows keep the slug — billing history, not reusable
        dup = await client.post("/v1/agents", headers=headers, json={"slug": "support-bot", "name": "Reborn"})
        assert dup.status_code == 409

    async def test_cross_org_404(self, client: AsyncClient, org_and_tokens) -> None:
        """Tenant isolation: org B can never see org A's agent."""
        a = org_and_tokens
        await _upgrade_to_pro(client, a)
        agent = await _create_agent(client, a, slug="org-a-agent")

        # A second org for the same user (also pro) probes A's agent id
        auth = {"Authorization": f"Bearer {a['access_token']}"}
        second = await client.post("/v1/orgs", headers=auth, json={"name": "Second Org"})
        assert second.status_code == 201
        b = second.json()
        b_headers = {**auth, "X-Org-Id": b["id"]}
        await client.post("/v1/billing/checkout", headers=b_headers, json={"plan_key": "pro"})
        await client.post("/v1/billing/checkout/confirm", headers=b_headers, json={"plan_key": "pro"})

        res = await client.get(f"/v1/agents/{agent['id']}", headers=b_headers)
        assert res.status_code == 404

    async def test_unknown_agent_404(self, client: AsyncClient, org_and_tokens) -> None:
        await _upgrade_to_pro(client, org_and_tokens)
        res = await client.get(
            "/v1/agents/00000000-0000-0000-0000-000000000000",
            headers=org_headers(org_and_tokens),
        )
        assert res.status_code == 404


class TestAgentEvents:
    async def test_registry_mutations_emit_outbox_events(self, client: AsyncClient, org_and_tokens) -> None:
        await _upgrade_to_pro(client, org_and_tokens)
        headers = org_headers(org_and_tokens)
        agent = await _create_agent(client, org_and_tokens)
        await client.patch(f"/v1/agents/{agent['id']}", headers=headers, json={"name": "v2"})
        await client.post(f"/v1/agents/{agent['id']}/disable", headers=headers)

        from sqlalchemy import select

        from synapse_saas.audit.models import OutboxEvent
        from synapse_saas.core.db import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OutboxEvent.event_type).where(OutboxEvent.aggregate_id == agent["id"])
                    )
                )
                .scalars()
                .all()
            )
        assert "agent.registered" in rows
        assert "agent.updated" in rows
        assert "agent.disabled" in rows


class TestAiMetering:
    async def test_pro_plan_enforces_ai_token_limit_with_402(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        """The runtime integration shape: consume BEFORE spend → 402 + hints."""
        await _upgrade_to_pro(client, org_and_tokens)
        headers = org_headers(org_and_tokens)

        # Pro includes 2,000,000 tokens — a 3M request must 402
        res = await client.post(
            "/v1/usage/consume",
            headers=headers,
            json={"events": [{"metric": "ai_tokens", "quantity": 3_000_000}]},
        )
        assert res.status_code == 402
        body = res.json()
        assert body["metric"] == "ai_tokens"  # extras merge at top level
        assert body["upgrade_url"]

        # Within plan: consumed and metered
        ok = await client.post(
            "/v1/usage/consume",
            headers=headers,
            json={"events": [{"metric": "ai_tokens", "quantity": 1_500_000}]},
        )
        assert ok.status_code == 200

    async def test_ai_token_overage_bills_on_invoice(self, client: AsyncClient, org_and_tokens) -> None:
        """2.5M used vs 2M included → 500k overage → ₱100 at ₱0.20/1k."""
        await _upgrade_to_pro(client, org_and_tokens)
        headers = org_headers(org_and_tokens)

        # record (not consume): enforcement blocked the 402 already; period-end
        # billing charges what actually ran
        await client.post(
            "/v1/usage/events",
            headers=headers,
            json={"events": [{"metric": "ai_tokens", "quantity": 2_500_000}]},
        )
        draft = await client.post("/v1/billing/invoices/draft", headers=headers, json={})
        assert draft.status_code == 201
        invoice = draft.json()
        overage = [line for line in invoice["lines"] if line["kind"] == "overage"]
        assert overage, f"expected token overage line, got {invoice['lines']}"
        assert overage[0]["metric"] == "ai_tokens"
        assert overage[0]["quantity"] == 500_000  # 2.5M used - 2M included
        assert overage[0]["amount_cents"] == 10_000  # 500k units at ₱0.20/1k = ₱100
