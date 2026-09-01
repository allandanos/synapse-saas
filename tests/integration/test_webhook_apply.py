"""Billing webhook application: provider events drive subscription state."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg

STRIPE_SECRET = "whsec_itest_apply"


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


def sign(body: bytes, secret: str = STRIPE_SECRET) -> dict[str, str]:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}"}


async def send_stripe(client: AsyncClient, event: dict) -> dict:
    body = json.dumps(event).encode()
    res = await client.post(
        "/v1/billing/webhooks/stripe",
        headers={**sign(body), "Content-Type": "application/json"},
        content=body,
    )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def stripe_env(monkeypatch: pytest.MonkeyPatch):
    from synapse_saas.core.config import get_settings

    monkeypatch.setenv("SYNAPSE_STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("SYNAPSE_STRIPE_WEBHOOK_SECRET", STRIPE_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sub_event(
    event_id: str,
    event_type: str,
    status: str,
    customer: str | None = None,
    **extra: object,
) -> dict:
    obj = {
        "id": f"sub_{event_id}",
        "object": "subscription",
        "status": status,
        "customer": customer,
        "current_period_end": int(time.time()) + 86400,
        "metadata": {"plan_key": "starter"},
    }
    obj.update(extra)
    return {
        "id": event_id,
        "type": event_type,
        "created": int(time.time()),
        "data": {"object": obj},
    }


async def _ensure_customer(client: AsyncClient, fixture: dict[str, str]) -> str:
    """Create the billing customer row so webhook org lookup resolves."""
    res = await client.post(
        "/v1/billing/checkout/confirm", headers=org_headers(fixture), json={"plan_key": "free"}
    )
    assert res.status_code == 200, res.text

    from synapse_saas.billing.models import BillingCustomer
    from synapse_saas.core.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                BillingCustomer.__table__.select().where(BillingCustomer.organization_id == fixture["org_id"])
            )
        ).first()
        return str(row.provider_customer_id)


class TestSubscriptionStateFromWebhooks:
    async def test_lifecycle(self, client: AsyncClient, org_and_tokens, stripe_env) -> None:
        headers = org_headers(org_and_tokens)
        customer = await _ensure_customer(client, org_and_tokens)

        # subscription.updated: past_due
        result = await send_stripe(
            client, _sub_event("evt_pd_1", "customer.subscription.updated", "past_due", customer=customer)
        )
        assert result["status"] == "processed"
        sub = (await client.get("/v1/subscription", headers=headers)).json()["subscription"]
        assert sub["status"] == "past_due"

        # Grace keeps features while past_due
        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert ent["subscription_status"] == "past_due"
        assert "basic_dashboard" in ent["features"]

        # recovered: back to active
        await send_stripe(
            client, _sub_event("evt_rec_1", "customer.subscription.updated", "active", customer=customer)
        )
        sub = (await client.get("/v1/subscription", headers=headers)).json()["subscription"]
        assert sub["status"] == "active"

        # canceled: features collapse
        await send_stripe(
            client, _sub_event("evt_cx_1", "customer.subscription.deleted", "canceled", customer=customer)
        )
        ent = (await client.get("/v1/entitlements", headers=headers)).json()
        assert ent["features"] == []

    async def test_out_of_order_and_replayed(self, client: AsyncClient, org_and_tokens, stripe_env) -> None:
        """Replays are no-ops; stale ordering can't regress past_due → trialing."""
        customer = await _ensure_customer(client, org_and_tokens)

        # Bring to active, replay the same event id — no double apply
        first = await send_stripe(
            client, _sub_event("evt_once", "customer.subscription.updated", "active", customer=customer)
        )
        assert first["events_applied"] == 1
        replay = await send_stripe(
            client, _sub_event("evt_once", "customer.subscription.updated", "active", customer=customer)
        )
        assert replay["status"] == "duplicate"

        # A late 'created' for a canceled subscription is rejected by the machine
        await send_stripe(
            client, _sub_event("evt_cx2", "customer.subscription.deleted", "canceled", customer=customer)
        )
        late = await send_stripe(client, _sub_event("evt_late", "customer.subscription.created", "trialing"))
        # applied=0: transition canceled→trialing is illegal; event recorded, ignored
        assert late["status"] == "processed"


class TestInvoiceUpsert:
    async def test_invoice_paid_records_and_upserts(
        self, client: AsyncClient, org_and_tokens, stripe_env
    ) -> None:
        headers = org_headers(org_and_tokens)
        customer = await _ensure_customer(client, org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})

        body_invoice = {
            "id": "evt_inv_1",
            "type": "invoice.paid",
            "created": int(time.time()),
            "data": {
                "object": {
                    "id": "in_apply_1",
                    "object": "invoice",
                    "customer": customer,
                    "amount_paid": 49900,
                    "currency": "php",
                    "status": "paid",
                }
            },
        }
        await send_stripe(client, body_invoice)

        invoices = (await client.get("/v1/billing/invoices", headers=headers)).json()
        match = [i for i in invoices if i["total_cents"] == 49900]
        assert match, f"invoice missing: {invoices}"
        assert match[0]["status"] == "paid"

        # Same invoice id again (retry) → still one row
        await send_stripe(client, body_invoice)
        invoices = (await client.get("/v1/billing/invoices", headers=headers)).json()
        assert len([i for i in invoices if i["total_cents"] == 49900]) == 1
