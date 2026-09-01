"""Provider HTTP paths via respx — no network, real request/response shapes."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from synapse_saas.billing.providers.stripe_provider import StripeBillingProvider

pytestmark = pytest.mark.asyncio


@pytest.fixture
def http() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://api.stripe.com")


@pytest.fixture
def provider(http: httpx.AsyncClient) -> StripeBillingProvider:
    return StripeBillingProvider(http, secret_key="sk_test_x", webhook_secret="whsec_x")


class TestCustomer:
    @respx.mock
    async def test_create_customer(self, provider: StripeBillingProvider) -> None:
        from synapse_saas.billing.protocol import CreateCustomerRequest

        respx.post("https://api.stripe.com/v1/customers").mock(
            return_value=Response(200, json={"id": "cus_123"})
        )
        ref = await provider.create_customer(
            CreateCustomerRequest(email="a@b.example", name="A", organization_id=None)
        )
        assert ref.provider_customer_id == "cus_123"

    @respx.mock
    async def test_api_error_raises(self, provider: StripeBillingProvider) -> None:
        from synapse_saas.billing.protocol import CreateCustomerRequest
        from synapse_saas.core.errors import BillingProviderError

        respx.post("https://api.stripe.com/v1/customers").mock(
            return_value=Response(402, json={"error": {"message": "card declined"}})
        )
        with pytest.raises(BillingProviderError, match="card declined"):
            await provider.create_customer(CreateCustomerRequest(email="a@b.example", organization_id=None))


class TestCheckout:
    @respx.mock
    async def test_checkout_session_returns_url(self, provider: StripeBillingProvider) -> None:
        from synapse_saas.billing.protocol import CreateCheckoutRequest

        route = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(
            return_value=Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/cs_1"})
        )
        result = await provider.create_checkout(
            CreateCheckoutRequest(
                plan_key="starter",
                plan_name="Starter",
                price_cents=49900,
                currency="PHP",
                interval="month",
                success_url="https://app.example.test/success",
            )
        )
        assert result.url == "https://checkout.stripe.com/cs_1"
        assert result.provider_checkout_id == "cs_1"

        # Form-encoded body carries the price in minor units
        from urllib.parse import unquote_plus

        body = unquote_plus(route.calls.last.request.content.decode())
        assert "unit_amount]=49900" in body  # line_items[0][price_data][unit_amount]
        assert "currency]=php" in body

    @respx.mock
    async def test_billing_portal(self, provider: StripeBillingProvider) -> None:
        respx.post("https://api.stripe.com/v1/billing_portal/sessions").mock(
            return_value=Response(200, json={"url": "https://billing.stripe.com/p_1"})
        )
        url = await provider.billing_portal_url("cus_1", return_url="https://app.example.test")
        assert url == "https://billing.stripe.com/p_1"


class TestSubscriptionApi:
    @respx.mock
    async def test_get_subscription(self, provider: StripeBillingProvider) -> None:
        respx.get("https://api.stripe.com/v1/subscriptions/sub_1").mock(
            return_value=Response(
                200,
                json={
                    "id": "sub_1",
                    "status": "active",
                    "customer": "cus_1",
                    "current_period_end": 1900000000,
                },
            )
        )
        ref = await provider.get_subscription("sub_1")
        assert ref.status == "active"
        assert ref.current_period_end is not None

    @respx.mock
    async def test_cancel_at_period_end(self, provider: StripeBillingProvider) -> None:
        route = respx.post("https://api.stripe.com/v1/subscriptions/sub_1").mock(
            return_value=Response(200, json={"id": "sub_1", "status": "active"})
        )
        await provider.cancel_subscription("sub_1", at_period_end=True)
        from urllib.parse import unquote_plus

        assert "cancel_at_period_end=true" in unquote_plus(route.calls.last.request.content.decode())

    @respx.mock
    async def test_change_plan_updates_item(self, provider: StripeBillingProvider) -> None:
        respx.get("https://api.stripe.com/v1/subscriptions/sub_1").mock(
            return_value=Response(
                200,
                json={"id": "sub_1", "status": "active", "items": {"data": [{"id": "si_1"}]}},
            )
        )
        respx.post("https://api.stripe.com/v1/subscriptions/sub_1").mock(
            return_value=Response(200, json={"id": "sub_1", "status": "active"})
        )
        from synapse_saas.billing.protocol import ChangePlanRequest

        ref = await provider.change_plan(
            "sub_1",
            ChangePlanRequest(plan_key="pro", price_cents=199900, currency="PHP", interval="month"),
        )
        assert ref.provider_subscription_id == "sub_1"


class TestInvoices:
    @respx.mock
    async def test_list_invoices(self, provider: StripeBillingProvider) -> None:
        respx.get("https://api.stripe.com/v1/invoices").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        {
                            "id": "in_1",
                            "number": "INV-1",
                            "status": "paid",
                            "total": 199900,
                            "currency": "php",
                            "created": 1900000000,
                            "status_transitions": {"paid_at": 1900000100},
                        }
                    ]
                },
            )
        )
        invoices = await provider.list_invoices("cus_1")
        assert len(invoices) == 1
        assert invoices[0].total_cents == 199900
        assert invoices[0].status == "paid"
        assert invoices[0].paid_at is not None
