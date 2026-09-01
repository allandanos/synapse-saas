"""PayMongo + Xendit HTTP paths via respx."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from synapse_saas.billing.protocol import (
    CreateCheckoutRequest,
    CreateSubscriptionRequest,
)
from synapse_saas.billing.providers.paymongo_provider import PayMongoBillingProvider
from synapse_saas.billing.providers.xendit_provider import XenditBillingProvider

pytestmark = pytest.mark.asyncio


@pytest.fixture
def paymongo() -> PayMongoBillingProvider:
    return PayMongoBillingProvider(httpx.AsyncClient(), secret_key="sk_pm", webhook_secret="w")


@pytest.fixture
def xendit() -> XenditBillingProvider:
    return XenditBillingProvider(httpx.AsyncClient(), secret_key="sk_xd", webhook_token="t")


CHECKOUT = CreateCheckoutRequest(
    plan_key="starter",
    plan_name="Starter",
    price_cents=49900,
    currency="PHP",
    interval="month",
    success_url="https://app.example.test/ok",
    organization_id=None,
)


class TestPayMongo:
    @respx.mock
    async def test_checkout_session(self, paymongo: PayMongoBillingProvider) -> None:
        respx.post("https://api.paymongo.com/v1/checkout_sessions").mock(
            return_value=Response(
                200,
                json={
                    "data": {
                        "id": "cs_pm_1",
                        "attributes": {"checkout_url": "https://checkout.paymongo.com/c/1"},
                    }
                },
            )
        )
        result = await paymongo.create_checkout(CHECKOUT)
        assert result.url == "https://checkout.paymongo.com/c/1"

    @respx.mock
    async def test_auth_header_is_basic(self, paymongo: PayMongoBillingProvider) -> None:
        import base64

        route = respx.post("https://api.paymongo.com/v1/checkout_sessions").mock(
            return_value=Response(
                200,
                json={"data": {"id": "cs_pm_2", "attributes": {"checkout_url": "https://x"}}},
            )
        )
        await paymongo.create_checkout(CHECKOUT)
        auth = route.calls.last.request.headers["Authorization"]
        expected = base64.b64encode(b"sk_pm:").decode()
        assert auth == f"Basic {expected}"

    async def test_local_subscription(self, paymongo: PayMongoBillingProvider) -> None:
        """No hosted recurring: provider mints a local reference."""
        ref = await paymongo.create_subscription(
            CreateSubscriptionRequest(
                plan_key="starter",
                price_cents=49900,
                currency="PHP",
                interval="month",
                provider_customer_id="c",
            )
        )
        assert ref.status == "active"
        assert ref.provider_subscription_id.startswith("paymongosub_")

    async def test_cancel_and_get(self, paymongo: PayMongoBillingProvider) -> None:
        canceled = await paymongo.cancel_subscription("sub_x")
        assert canceled.status == "canceled"
        got = await paymongo.get_subscription("sub_x")
        assert got.status == "active"

    async def test_invoices_empty(self, paymongo: PayMongoBillingProvider) -> None:
        assert await paymongo.list_invoices("c") == []


class TestXendit:
    @respx.mock
    async def test_invoice_checkout(self, xendit: XenditBillingProvider) -> None:
        route = respx.post("https://api.xendit.co/invoices").mock(
            return_value=Response(200, json={"id": "inv_1", "invoice_url": "https://checkout.xendit.co/i/1"})
        )
        result = await xendit.create_checkout(CHECKOUT)
        assert result.url == "https://checkout.xendit.co/i/1"

        # Xendit takes major units: 49900 centavos → 499.00
        import json as json_mod

        body = json_mod.loads(route.calls.last.request.content)
        assert body["amount"] == 499.0

    @respx.mock
    async def test_customers(self, xendit: XenditBillingProvider) -> None:
        from synapse_saas.billing.protocol import CreateCustomerRequest

        respx.post("https://api.xendit.co/customers").mock(
            return_value=Response(200, json={"id": "cust_xnd_1"})
        )
        ref = await xendit.create_customer(CreateCustomerRequest(email="a@b.example", organization_id=None))
        assert ref.provider_customer_id == "cust_xnd_1"

    @respx.mock
    async def test_list_invoices_major_units(self, xendit: XenditBillingProvider) -> None:
        respx.get("https://api.xendit.co/v2/invoices").mock(
            return_value=Response(
                200,
                json={"data": [{"id": "inv_2", "amount": 1999.0, "currency": "PHP", "status": "PAID"}]},
            )
        )
        invoices = await xendit.list_invoices("c")
        assert invoices[0].total_cents == 199900
        assert invoices[0].status == "paid"

    @respx.mock
    async def test_api_error_raises(self, xendit: XenditBillingProvider) -> None:
        from synapse_saas.core.errors import BillingProviderError

        respx.post("https://api.xendit.co/invoices").mock(return_value=Response(401, text="unauthorized"))
        with pytest.raises(BillingProviderError):
            await xendit.create_checkout(CHECKOUT)
