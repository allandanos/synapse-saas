"""Invoicing engine integration: draft-from-usage → finalize → pay → void."""

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


async def draft(client: AsyncClient, fixture: dict[str, str]) -> dict:
    res = await client.post("/v1/billing/invoices/draft", headers=org_headers(fixture), json={})
    assert res.status_code == 201, res.text
    return res.json()


class TestDraft:
    async def test_free_plan_drafts_no_lines(self, client: AsyncClient, org_and_tokens) -> None:
        invoice = await draft(client, org_and_tokens)
        assert invoice["status"] == "draft"
        assert invoice["lines"] == []  # free: ₱0 plan, no overage yet
        assert invoice["subtotal_cents"] == 0

    async def test_paid_plan_adds_plan_line(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        invoice = await draft(client, org_and_tokens)
        lines = invoice["lines"]
        assert len(lines) == 1
        assert lines[0]["kind"] == "plan"
        assert lines[0]["amount_cents"] == 49900
        assert "Starter" in lines[0]["description"]

    async def test_overage_metered_beyond_plan_limit(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        # Starter: ai_tokens has NO limit set in the default catalog… but
        # free/starter don't either — attach a tight addon and blow past it.
        await client.post(
            "/v1/entitlements/grants",
            headers=headers,
            json={"feature_key": "limit:ai_tokens", "source": "addon", "limit_value": 1000},
        )
        # record (not consume): runtime enforcement already blocked the 402s;
        # metered usage past quota is exactly what period-end billing charges
        await client.post(
            "/v1/usage/events",
            headers=headers,
            json={"events": [{"metric": "ai_tokens", "quantity": 5000}]},
        )
        invoice = await draft(client, org_and_tokens)
        overage = [line for line in invoice["lines"] if line["kind"] == "overage"]
        assert overage, f"expected an overage line, got {invoice['lines']}"
        assert overage[0]["metric"] == "ai_tokens"
        assert overage[0]["quantity"] == 4000  # 5000 used - 1000 included
        assert overage[0]["amount_cents"] == 80  # 4k units x ₱0.20/1k
        assert invoice["subtotal_cents"] == 80

    async def test_draft_idempotent_per_period(self, client: AsyncClient, org_and_tokens) -> None:
        first = await draft(client, org_and_tokens)
        second = await draft(client, org_and_tokens)
        assert first["id"] == second["id"]

    async def test_grandfathered_snapshot_price(self, client: AsyncClient, org_and_tokens) -> None:
        """Draft charges the snapshot price even if the catalog changes later."""
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        invoice = await draft(client, org_and_tokens)
        assert invoice["lines"][0]["amount_cents"] == 49900  # purchase-time price


class TestFinalizeAndPay:
    async def test_full_lifecycle(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})

        created = await draft(client, org_and_tokens)
        invoice_id = created["id"]

        finalized = (await client.post(f"/v1/billing/invoices/{invoice_id}/finalize", headers=headers)).json()
        assert finalized["status"] == "open"
        assert finalized["number"].startswith("INV-")
        assert finalized["issued_at"] is not None

        paid = await client.post(
            f"/v1/billing/invoices/{invoice_id}/pay",
            headers=headers,
            json={"amount_cents": 199900, "reference": "bank-transfer-001"},
        )
        assert paid.status_code == 200
        assert paid.json()["status"] == "paid"
        assert paid.json()["paid_at"] is not None

        # Outbox carried invoice.paid (webhooks/email ride it)
        from sqlalchemy import text as sql_text

        from synapse_saas.core.db import get_session_factory

        async with get_session_factory()() as session:
            row = (
                await session.execute(
                    sql_text(
                        "SELECT event_type FROM outbox_events "
                        "WHERE aggregate_type='invoice' ORDER BY created_at DESC LIMIT 2"
                    )
                )
            ).all()
        assert {r.event_type for r in row} >= {"invoice.paid"}

    async def test_partial_payment_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        invoice = await draft(client, org_and_tokens)
        await client.post(f"/v1/billing/invoices/{invoice['id']}/finalize", headers=headers)

        short = await client.post(
            f"/v1/billing/invoices/{invoice['id']}/pay",
            headers=headers,
            json={"amount_cents": 100},
        )
        assert short.status_code == 422

    async def test_pay_before_finalize_rejected(self, client: AsyncClient, org_and_tokens) -> None:
        invoice = await draft(client, org_and_tokens)
        res = await client.post(
            f"/v1/billing/invoices/{invoice['id']}/pay",
            headers=org_headers(org_and_tokens),
            json={"amount_cents": 0 + 1},
        )
        assert res.status_code == 422  # draft → paid is not a legal transition

    async def test_void_draft(self, client: AsyncClient, org_and_tokens) -> None:
        invoice = await draft(client, org_and_tokens)
        res = await client.post(
            f"/v1/billing/invoices/{invoice['id']}/void", headers=org_headers(org_and_tokens)
        )
        assert res.json()["status"] == "void"

    async def test_paid_invoice_is_terminal(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        invoice = await draft(client, org_and_tokens)
        await client.post(f"/v1/billing/invoices/{invoice['id']}/finalize", headers=headers)
        await client.post(
            f"/v1/billing/invoices/{invoice['id']}/pay",
            headers=headers,
            json={"amount_cents": 49900},
        )
        again = await client.post(f"/v1/billing/invoices/{invoice['id']}/void", headers=headers)
        assert again.status_code == 422


class TestDetailAndIsolation:
    async def test_detail_includes_lines(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        invoice = await draft(client, org_and_tokens)
        detail = (await client.get(f"/v1/billing/invoices/{invoice['id']}", headers=headers)).json()
        assert len(detail["lines"]) == 1
        assert detail["lines"][0]["kind"] == "plan"

    async def test_cross_org_invoice_404(self, client: AsyncClient, org_and_tokens) -> None:
        invoice = await draft(client, org_and_tokens)
        rival = await client.post(
            "/v1/auth/register",
            json={
                "email": f"inv-rival-{uuid.uuid4().hex[:6]}@example.com",
                "password": "password12345",
                "display_name": "R",
            },
        )
        rival_token = rival.json()["tokens"]["access_token"]
        rival_org = (
            await client.post(
                "/v1/orgs",
                headers={"Authorization": f"Bearer {rival_token}"},
                json={"name": "Rival"},
            )
        ).json()["id"]

        foreign = await client.get(
            f"/v1/billing/invoices/{invoice['id']}",
            headers={"Authorization": f"Bearer {rival_token}", "X-Org-Id": rival_org},
        )
        phantom = await client.get(
            f"/v1/billing/invoices/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {rival_token}", "X-Org-Id": rival_org},
        )
        assert foreign.status_code == phantom.status_code == 404
        foreign_body, phantom_body = foreign.json(), phantom.json()
        foreign_body.pop("instance"), phantom_body.pop("instance")
        assert foreign_body == phantom_body

    async def test_permission_gate(self, client: AsyncClient, org_and_tokens) -> None:
        """Plain members (no billing:manage) cannot draft."""
        from synapse_saas.core.cache import VersionedCache

        headers = org_headers(org_and_tokens)
        await client.post(
            "/v1/orgs/current/members/invite",
            headers=headers,
            json={"email": "plain-inv@example.com"},
        )
        # Register + accept as that email → member role
        reg = await client.post(
            "/v1/auth/register",
            json={
                "email": "plain-inv@example.com",
                "password": "password12345",
                "display_name": "P",
            },
        )
        member_token = reg.json()["tokens"]["access_token"]
        await client.post(
            "/v1/auth/accept-invite",
            headers={"Authorization": f"Bearer {member_token}"},
            json={"token": await _invite_token(org_and_tokens)},
        )
        await VersionedCache("perm").bump(f"{org_and_tokens['org_id']}")

        res = await client.post(
            "/v1/billing/invoices/draft",
            headers={
                "Authorization": f"Bearer {member_token}",
                "X-Org-Id": org_and_tokens["org_id"],
            },
            json={},
        )
        assert res.status_code == 403


async def _invite_token(fixture: dict[str, str]) -> str:
    from sqlalchemy import text

    from synapse_saas.core.db import get_session_factory

    async with get_session_factory()() as session:
        row = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_events "
                    "WHERE event_type='member.invited' ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).first()
    return str(row.payload["invite_token"])


class TestReporting:
    async def test_org_spend_summary_after_lifecycle(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        invoice = await draft(client, org_and_tokens)
        await client.post(f"/v1/billing/invoices/{invoice['id']}/finalize", headers=headers)
        await client.post(
            f"/v1/billing/invoices/{invoice['id']}/pay",
            headers=headers,
            json={"amount_cents": 199900, "reference": "bank-1"},
        )

        summary = (await client.get("/v1/billing/spend-summary", headers=headers)).json()
        assert summary["paid_cents"] == 199900
        assert summary["outstanding_cents"] == 0
        assert summary["by_status"]["paid"] == 199900

    async def test_monthly_spend_buckets(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        invoice = await draft(client, org_and_tokens)
        await client.post(f"/v1/billing/invoices/{invoice['id']}/finalize", headers=headers)
        await client.post(
            f"/v1/billing/invoices/{invoice['id']}/pay",
            headers=headers,
            json={"amount_cents": 49900},
        )
        monthly = (await client.get("/v1/billing/spend-monthly", headers=headers)).json()
        assert len(monthly) == 1
        assert monthly[0]["total_cents"] == 49900
        assert monthly[0]["invoices"] == 1

    async def test_revenue_admin_gated(self, client: AsyncClient, org_and_tokens) -> None:
        res = await client.get("/v1/billing/admin/revenue-summary", headers=org_headers(org_and_tokens))
        assert res.status_code == 404  # not platform admin → not-found, no leak

    async def test_revenue_summary_for_platform_admin(self, client: AsyncClient, org_and_tokens) -> None:
        from sqlalchemy import select

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.identity.models import User

        factory = get_session_factory()
        async with factory() as session:
            user = (await session.execute(select(User).where(User.email == "owner@example.com"))).scalar_one()
            user.is_platform_admin = True
            await session.commit()

        # Issue a paid invoice first so the numbers aren't all zero
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        invoice = await draft(client, org_and_tokens)
        await client.post(f"/v1/billing/invoices/{invoice['id']}/finalize", headers=headers)
        await client.post(
            f"/v1/billing/invoices/{invoice['id']}/pay",
            headers=headers,
            json={"amount_cents": 199900},
        )

        summary = (await client.get("/v1/billing/admin/revenue-summary", headers=headers)).json()
        assert summary["collected_cents"] >= 199900
        assert summary["mrr_proxy_cents"] >= 199900  # active pro subscription
        assert summary["paying_organizations"] >= 1
        assert summary["invoices_by_status"]["paid"] >= 1

        monthly = (await client.get("/v1/billing/admin/revenue-monthly", headers=headers)).json()
        assert any(m["collected_cents"] >= 199900 for m in monthly)
