"""Paddle provider unit tests — signature verification + translation."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import pytest

from synapse_saas.billing.protocol import WebhookRequest
from synapse_saas.billing.providers.paddle_provider import PaddleBillingProvider
from synapse_saas.core.errors import WebhookSignatureInvalidError

SECRET = "pdl_ntfset_test"


def provider() -> PaddleBillingProvider:
    return PaddleBillingProvider(httpx.AsyncClient(), secret_key="pk_test", webhook_secret=SECRET)


def signed(body: bytes, secret: str = SECRET, *, timestamp: int | None = None) -> dict[str, str]:
    ts = timestamp or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"paddle-signature": f"ts={ts},h1={sig}"}


class TestVerification:
    async def test_valid_signature(self) -> None:
        body = json.dumps({"event_id": "evt_1", "event_type": "transaction.completed"}).encode()
        verified = await provider().verify_webhook(WebhookRequest(signed(body), body))
        assert verified.provider_event_id == "evt_1"

    async def test_tampered_body(self) -> None:
        body = json.dumps({"event_id": "evt_2", "event_type": "transaction.completed"}).encode()
        headers = signed(body)
        with pytest.raises(WebhookSignatureInvalidError):
            await provider().verify_webhook(WebhookRequest(headers, b"tampered"))

    async def test_wrong_secret(self) -> None:
        body = json.dumps({"event_id": "evt_3"}).encode()
        with pytest.raises(WebhookSignatureInvalidError):
            await provider().verify_webhook(WebhookRequest(signed(body, "wrong"), body))

    async def test_stale_timestamp(self) -> None:
        body = json.dumps({"event_id": "evt_4"}).encode()
        stale = int(time.time()) - 3600
        with pytest.raises(WebhookSignatureInvalidError):
            await provider().verify_webhook(WebhookRequest(signed(body, timestamp=stale), body))

    async def test_missing_header_and_secret(self) -> None:
        body = json.dumps({"event_id": "evt_5"}).encode()
        with pytest.raises(WebhookSignatureInvalidError):
            await provider().verify_webhook(WebhookRequest({}, body))

    async def test_unconfigured_secret_rejects(self) -> None:
        unconfigured = PaddleBillingProvider(httpx.AsyncClient(), secret_key="k", webhook_secret="")
        body = json.dumps({"event_id": "evt_6"}).encode()
        with pytest.raises(WebhookSignatureInvalidError):
            await unconfigured.verify_webhook(WebhookRequest(signed(body), body))


class TestTranslation:
    async def test_transaction_completed_translates(self) -> None:
        body = json.dumps(
            {
                "event_id": "evt_7",
                "event_type": "transaction.completed",
                "data": {
                    "id": "txn_1",
                    "custom_data": {"plan_key": "starter", "org_id": "org_1"},
                    "totals": {"total": 49900},
                    "currency_code": "php",
                },
            }
        ).encode()
        p = provider()
        verified = await p.verify_webhook(WebhookRequest(signed(body), body))
        events = p.translate_webhook(verified)
        assert len(events) == 1
        assert events[0].event_type == "checkout.completed"
        assert events[0].plan_key == "starter"
        assert events[0].amount_cents == 49900
        assert events[0].currency == "PHP"

    async def test_subscription_events_map(self) -> None:
        for paddle_type, canonical in [
            ("subscription.activated", "subscription.activated"),
            ("subscription.canceled", "subscription.canceled"),
            ("subscription.past_due", "subscription.past_due"),
        ]:
            body = json.dumps(
                {"event_id": "evt_8", "event_type": paddle_type, "data": {"id": "sub_1", "status": "active"}}
            ).encode()
            p = provider()
            verified = await p.verify_webhook(WebhookRequest(signed(body), body))
            events = p.translate_webhook(verified)
            assert events[0].event_type == canonical

    async def test_unknown_event_noop(self) -> None:
        body = json.dumps({"event_id": "evt_9", "event_type": "adjustment.created", "data": {}}).encode()
        p = provider()
        verified = await p.verify_webhook(WebhookRequest(signed(body), body))
        assert p.translate_webhook(verified) == []
