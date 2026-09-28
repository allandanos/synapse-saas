"""C3: a plan change reaches the payment provider — or is refused — and local
billing prorates instead of silently resetting the period.

Before: `/subscription/change` called only the local SubscriptionService, so
Stripe kept billing the old price, and every change reset the period to
now+30d with no credit for the unused part.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from synapse_saas.billing.protocol import (
    BillingCapability,
    BillingCustomerRef,
    BillingProvider,
    ChangePlanRequest,
    CheckoutResult,
    CreateCheckoutRequest,
    CreateCustomerRequest,
    CreateSubscriptionRequest,
    InvoiceRef,
    NormalizedBillingEvent,
    SubscriptionRef,
    VerifiedWebhook,
    WebhookRequest,
)
from tests.integration.conftest import owner_session_factory

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


class FakeHostedProvider(BillingProvider):
    """A Stripe-shaped provider: it bills recurring, so plan changes must go through it."""

    name = "fakehosted"
    supports = frozenset(
        {
            BillingCapability.HOSTED_CHECKOUT,
            BillingCapability.RECURRING_HOSTED,
            BillingCapability.WEBHOOK_SIGNED,
        }
    )

    def __init__(self) -> None:
        self.plan_changes: list[tuple[str, ChangePlanRequest]] = []

    async def create_customer(self, req: CreateCustomerRequest) -> BillingCustomerRef:
        return BillingCustomerRef(provider_customer_id="cus_fake", email=req.email, name=req.name)

    async def create_checkout(self, req: CreateCheckoutRequest) -> CheckoutResult:
        raise NotImplementedError

    async def create_subscription(self, req: CreateSubscriptionRequest) -> SubscriptionRef:
        raise NotImplementedError

    async def change_plan(self, provider_subscription_id: str, req: ChangePlanRequest) -> SubscriptionRef:
        self.plan_changes.append((provider_subscription_id, req))
        return SubscriptionRef(provider_subscription_id=provider_subscription_id, status="active")

    async def cancel_subscription(
        self, provider_subscription_id: str, *, at_period_end: bool = True
    ) -> SubscriptionRef:
        raise NotImplementedError

    async def get_subscription(self, provider_subscription_id: str) -> SubscriptionRef:
        raise NotImplementedError

    async def list_invoices(self, provider_customer_id: str, *, limit: int = 20) -> list[InvoiceRef]:
        return []

    async def verify_webhook(self, raw: WebhookRequest) -> VerifiedWebhook:
        raise NotImplementedError

    def translate_webhook(self, verified: VerifiedWebhook) -> list[NormalizedBillingEvent]:
        return []


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> FakeHostedProvider:
    provider = FakeHostedProvider()
    import synapse_saas.billing.service as billing_service

    monkeypatch.setattr(billing_service, "build_provider", lambda *a, **k: provider)
    return provider


async def _set_subscription(org_id: str, **values: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    async with owner_session_factory()() as session:
        await session.execute(
            text(f"UPDATE subscriptions SET {sets} WHERE organization_id = :org"),  # noqa: S608 — column names are ours
            {"org": org_id, **values},
        )
        await session.commit()


async def _subscription(org_id: str) -> dict[str, Any]:
    async with owner_session_factory()() as session:
        row = (
            await session.execute(
                text(
                    "SELECT plan_snapshot->>'key' AS plan_key, current_period_start, current_period_end, "
                    "provider, provider_subscription_id, pending_adjustments "
                    "FROM subscriptions WHERE organization_id = :org"
                ),
                {"org": org_id},
            )
        ).one()
        return dict(row._mapping)


class TestHostedProvider:
    async def test_change_calls_provider_change_plan(
        self, client: AsyncClient, org_and_tokens, hosted
    ) -> None:
        await _set_subscription(
            org_and_tokens["org_id"],
            provider="fakehosted",
            provider_subscription_id="sub_123",
            status="active",
        )
        before = await _subscription(org_and_tokens["org_id"])

        res = await client.post(
            "/v1/subscription/change", headers=org_headers(org_and_tokens), json={"plan_key": "pro"}
        )
        assert res.status_code == 200, res.text
        assert res.json()["plan"]["key"] == "pro"

        assert hosted.plan_changes == [("sub_123", ChangePlanRequest("pro", 199900, "PHP", "month"))]
        after = await _subscription(org_and_tokens["org_id"])
        assert after["plan_key"] == "pro"
        # The provider owns the billing cycle: the period is NOT reset locally
        assert after["current_period_end"] == before["current_period_end"]
        assert after["pending_adjustments"] == []  # and it owns proration too

    async def test_hosted_without_provider_subscription_409(
        self, client: AsyncClient, org_and_tokens, hosted
    ) -> None:
        """The free bootstrap subscription was never purchased through the provider."""
        res = await client.post(
            "/v1/subscription/change", headers=org_headers(org_and_tokens), json={"plan_key": "pro"}
        )
        assert res.status_code == 409, res.text
        body = res.json()
        assert body["title"] == "checkout required"  # problem titles are humanized
        assert body["checkout_url"] == "/v1/billing/checkout"
        assert hosted.plan_changes == []
        assert (await _subscription(org_and_tokens["org_id"]))["plan_key"] == "free"


class TestLocalProviderProration:
    """Manual provider (the test default): we bill, so we prorate."""

    async def test_free_to_paid_starts_a_fresh_cycle(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await _set_subscription(
            org_and_tokens["org_id"],
            current_period_start=datetime.now(UTC) - timedelta(days=20),
            current_period_end=datetime.now(UTC) + timedelta(days=10),
        )
        res = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        assert res.status_code == 200, res.text
        sub = await _subscription(org_and_tokens["org_id"])
        assert sub["current_period_start"] > datetime.now(UTC) - timedelta(minutes=1)  # reset to now
        assert sub["pending_adjustments"] == []  # nothing to prorate on ₱0

    async def test_paid_to_paid_keeps_the_period_and_credits_the_elapsed_part(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        now = datetime.now(UTC)
        await _set_subscription(
            org_and_tokens["org_id"],
            current_period_start=now - timedelta(days=15),
            current_period_end=now + timedelta(days=15),
        )

        res = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        assert res.status_code == 200, res.text
        sub = await _subscription(org_and_tokens["org_id"])
        assert sub["plan_key"] == "pro"
        assert abs((sub["current_period_end"] - (now + timedelta(days=15))).total_seconds()) < 1
        (adjustment,) = sub["pending_adjustments"]
        assert adjustment["kind"] == "proration"
        assert adjustment["from_plan"] == "starter" and adjustment["to_plan"] == "pro"
        # half the period at the old price: (49900 - 199900) * 0.5 = -75000 (a credit)
        assert -75100 <= adjustment["amount_cents"] <= -74900

        # The period's invoice bills pro in full and carries the credit — once.
        draft = (await client.post("/v1/billing/invoices/draft", headers=headers, json={})).json()
        kinds = {line["kind"]: line for line in draft["lines"]}
        assert kinds["plan"]["amount_cents"] == 199900
        assert kinds["credit"]["amount_cents"] == adjustment["amount_cents"]
        assert (
            kinds["credit"]["quantity"] * kinds["credit"]["unit_amount_cents"]
            == kinds["credit"]["amount_cents"]
        )
        assert draft["subtotal_cents"] == 199900 + adjustment["amount_cents"]
        assert (await _subscription(org_and_tokens["org_id"]))["pending_adjustments"] == []

    async def test_downgrade_charges_the_elapsed_part_at_the_old_price(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "pro"})
        now = datetime.now(UTC)
        await _set_subscription(
            org_and_tokens["org_id"],
            current_period_start=now - timedelta(days=15),
            current_period_end=now + timedelta(days=15),
        )
        res = await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        assert res.status_code == 200, res.text
        (adjustment,) = (await _subscription(org_and_tokens["org_id"]))["pending_adjustments"]
        assert 74900 <= adjustment["amount_cents"] <= 75100  # (199900 - 49900) * 0.5

        draft = (await client.post("/v1/billing/invoices/draft", headers=headers, json={})).json()
        kinds = {line["kind"]: line for line in draft["lines"]}
        assert kinds["plan"]["amount_cents"] == 49900
        assert kinds["custom"]["amount_cents"] == adjustment["amount_cents"]
        assert draft["subtotal_cents"] == 49900 + adjustment["amount_cents"]

    async def test_credit_larger_than_the_invoice_carries_forward(
        self, client: AsyncClient, org_and_tokens
    ) -> None:
        """An operator credit note bigger than the period's charges never yields a negative invoice."""
        headers = org_headers(org_and_tokens)
        await client.post("/v1/subscription/change", headers=headers, json={"plan_key": "starter"})
        import json

        await _set_subscription(
            org_and_tokens["org_id"],
            pending_adjustments=json.dumps(
                [
                    {
                        "kind": "credit_note",
                        "amount_cents": -80000,
                        "description": "Goodwill credit",
                        "created_at": "x",
                    }
                ]
            ),
        )
        draft = (await client.post("/v1/billing/invoices/draft", headers=headers, json={})).json()
        assert draft["subtotal_cents"] == 0 and draft["total_cents"] == 0
        (carry,) = (await _subscription(org_and_tokens["org_id"]))["pending_adjustments"]
        assert carry["kind"] == "credit_carryover"
        assert carry["amount_cents"] == -(80000 - 49900)
