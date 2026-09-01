"""Provider webhook signature verification — all four, no network.

The security-critical half of every provider: valid signatures pass; tampered
bodies, wrong secrets, stale timestamps, and malformed headers all reject.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from synapse_saas.billing.protocol import WebhookRequest
from synapse_saas.billing.providers.manual_provider import ManualBillingProvider
from synapse_saas.billing.providers.paymongo_provider import PayMongoBillingProvider
from synapse_saas.billing.providers.stripe_provider import StripeBillingProvider
from synapse_saas.billing.providers.xendit_provider import XenditBillingProvider
from synapse_saas.core.errors import WebhookSignatureInvalidError

SECRET = "whsec_test_secret"


def stripe_body(event_id: str = "evt_1") -> bytes:
    return json.dumps({"id": event_id, "type": "invoice.paid", "created": int(time.time())}).encode()


def signed_headers(
    body: bytes,
    secret: str,
    *,
    timestamp: int | None = None,
    header: str = "stripe-signature",
) -> dict[str, str]:
    ts = timestamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {header: f"t={ts},v1={sig}"}


def stripe_provider() -> StripeBillingProvider:
    import httpx

    return StripeBillingProvider(httpx.AsyncClient(), secret_key="sk_x", webhook_secret=SECRET)


class TestStripe:
    async def test_valid_signature_accepted(self) -> None:
        body = stripe_body()
        provider = stripe_provider()
        verified = await provider.verify_webhook(WebhookRequest(signed_headers(body, SECRET), body))
        assert verified.provider_event_id == "evt_1"

    async def test_tampered_body_rejected(self) -> None:
        body = stripe_body()
        headers = signed_headers(body, SECRET)
        with pytest.raises(WebhookSignatureInvalidError):
            await stripe_provider().verify_webhook(WebhookRequest(headers, b"tampered"))

    async def test_wrong_secret_rejected(self) -> None:
        body = stripe_body()
        headers = signed_headers(body, "whsec_other")
        with pytest.raises(WebhookSignatureInvalidError):
            await stripe_provider().verify_webhook(WebhookRequest(headers, body))

    async def test_stale_timestamp_rejected(self) -> None:
        body = stripe_body()
        stale = int(time.time()) - 3600
        headers = signed_headers(body, SECRET, timestamp=stale)
        with pytest.raises(WebhookSignatureInvalidError):
            await stripe_provider().verify_webhook(WebhookRequest(headers, body))

    async def test_malformed_header_rejected(self) -> None:
        body = stripe_body()
        with pytest.raises(WebhookSignatureInvalidError):
            await stripe_provider().verify_webhook(WebhookRequest({"stripe-signature": "garbage"}, body))

    async def test_missing_header_rejected(self) -> None:
        with pytest.raises(WebhookSignatureInvalidError):
            await stripe_provider().verify_webhook(WebhookRequest({}, stripe_body()))


class TestPayMongo:
    def _provider(self) -> PayMongoBillingProvider:
        import httpx

        return PayMongoBillingProvider(httpx.AsyncClient(), secret_key="sk_x", webhook_secret=SECRET)

    async def test_valid_signature_accepted(self) -> None:
        body = json.dumps({"id": "evt_pm", "type": "payment.paid", "data": {"attributes": {}}}).encode()
        headers = signed_headers(body, SECRET, header="paymongo-signature")
        verified = await self._provider().verify_webhook(WebhookRequest(headers, body))
        assert verified.provider_event_id == "evt_pm"

    async def test_wrong_secret_rejected(self) -> None:
        body = json.dumps({"data": {}}).encode()
        headers = signed_headers(body, "other", header="paymongo-signature")
        with pytest.raises(WebhookSignatureInvalidError):
            await self._provider().verify_webhook(WebhookRequest(headers, body))


class TestXendit:
    def _provider(self) -> XenditBillingProvider:
        import httpx

        return XenditBillingProvider(httpx.AsyncClient(), secret_key="sk_x", webhook_token=SECRET)

    async def test_valid_token_accepted(self) -> None:
        body = json.dumps({"id": "xnd_1", "status": "PAID"}).encode()
        verified = await self._provider().verify_webhook(WebhookRequest({"x-callback-token": SECRET}, body))
        assert verified.provider_event_id == "xnd_1"

    async def test_wrong_token_rejected(self) -> None:
        with pytest.raises(WebhookSignatureInvalidError):
            await self._provider().verify_webhook(WebhookRequest({"x-callback-token": "nope"}, b"{}"))

    async def test_missing_token_rejected(self) -> None:
        with pytest.raises(WebhookSignatureInvalidError):
            await self._provider().verify_webhook(WebhookRequest({}, b"{}"))

    async def test_unconfigured_token_rejects_everything(self) -> None:
        import httpx

        provider = XenditBillingProvider(httpx.AsyncClient(), secret_key="k", webhook_token="")
        with pytest.raises(WebhookSignatureInvalidError):
            await provider.verify_webhook(WebhookRequest({"x-callback-token": "anything"}, b"{}"))


class TestManual:
    async def test_valid_token_accepted(self) -> None:
        provider = ManualBillingProvider(webhook_token="tok")
        verified = await provider.verify_webhook(
            WebhookRequest({"x-manual-token": "tok"}, json.dumps({"id": "m1"}).encode())
        )
        assert verified.provider_event_id == "m1"

    async def test_bad_token_rejected(self) -> None:
        provider = ManualBillingProvider(webhook_token="tok")
        with pytest.raises(WebhookSignatureInvalidError):
            await provider.verify_webhook(WebhookRequest({"x-manual-token": "wrong"}, b"{}"))


class TestTranslation:
    async def test_stripe_invoice_paid_translates(self) -> None:
        body = json.dumps(
            {
                "id": "evt_2",
                "type": "invoice.paid",
                "created": int(time.time()),
                "data": {
                    "object": {
                        "id": "in_2",
                        "customer": "cus_2",
                        "amount_paid": 199900,
                        "currency": "php",
                        "status": "paid",
                    }
                },
            }
        ).encode()
        provider = stripe_provider()
        verified = await provider.verify_webhook(WebhookRequest(signed_headers(body, SECRET), body))
        events = provider.translate_webhook(verified)
        assert len(events) == 1
        assert events[0].event_type == "invoice.paid"
        assert events[0].provider_customer_id == "cus_2"
        assert events[0].amount_cents == 199900

    async def test_unknown_event_type_yields_nothing(self) -> None:
        body = json.dumps({"id": "evt_3", "type": "something.odd", "created": int(time.time())}).encode()
        provider = stripe_provider()
        verified = await provider.verify_webhook(WebhookRequest(signed_headers(body, SECRET), body))
        assert provider.translate_webhook(verified) == []

    async def test_xendit_paid_translates(self) -> None:
        import httpx

        provider = XenditBillingProvider(httpx.AsyncClient(), secret_key="k", webhook_token="t")
        verified = await provider.verify_webhook(
            WebhookRequest(
                {"x-callback-token": "t"},
                json.dumps({"id": "xnd_2", "status": "PAID", "amount": 1999.0}).encode(),
            )
        )
        events = provider.translate_webhook(verified)
        assert events[0].event_type == "invoice.paid"
        assert events[0].amount_cents == 199900

    async def test_manual_subscription_activated_translates(self) -> None:
        provider = ManualBillingProvider(webhook_token="t")
        verified = await provider.verify_webhook(
            WebhookRequest(
                {"x-manual-token": "t"},
                json.dumps(
                    {
                        "id": "m2",
                        "type": "manual.subscription.activated",
                        "data": {"plan_key": "starter"},
                    }
                ).encode(),
            )
        )
        events = provider.translate_webhook(verified)
        assert events[0].event_type == "subscription.activated"
        assert events[0].plan_key == "starter"
