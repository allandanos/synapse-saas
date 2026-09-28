"""C1: client-side checkout confirmation is only valid for offline-payment providers.

With Stripe/Paddle/Xendit/PayMongo, activation must come from the provider's
signed webhook. Before this guard, any billing:manage holder could activate a
paid plan with one POST and no payment.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {fixture['access_token']}", "X-Org-Id": fixture["org_id"]}


@pytest.fixture
def stripe_provider(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from synapse_saas.core.config import get_settings

    monkeypatch.setenv("SYNAPSE_BILLING_PROVIDER", "stripe")
    monkeypatch.setenv("SYNAPSE_STRIPE_SECRET_KEY", "sk_test_placeholder")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestConfirmGuard:
    async def test_confirm_is_409_under_stripe(
        self, stripe_provider, client: AsyncClient, org_and_tokens
    ) -> None:
        res = await client.post(
            "/v1/billing/checkout/confirm", headers=org_headers(org_and_tokens), json={"plan_key": "pro"}
        )
        assert res.status_code == 409, res.text
        body = res.json()
        assert body["type"].endswith("/checkout_confirm_not_allowed")
        assert body["provider"] == "stripe"

        # …and the org stayed on free: no free upgrade happened
        sub = await client.get("/v1/subscription", headers=org_headers(org_and_tokens))
        current = sub.json().get("subscription")
        assert current is None or current["plan_snapshot"]["key"] == "free"

    async def test_confirm_ok_under_manual(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post("/v1/billing/checkout", headers=headers, json={"plan_key": "pro"})
        res = await client.post("/v1/billing/checkout/confirm", headers=headers, json={"plan_key": "pro"})
        assert res.status_code == 200, res.text
        assert res.json()["plan_key"] == "pro"

    async def test_capability_is_explicit_per_provider(self) -> None:
        from synapse_saas.billing.protocol import BillingCapability
        from synapse_saas.billing.providers.manual_provider import ManualBillingProvider
        from synapse_saas.billing.providers.paddle_provider import PaddleBillingProvider
        from synapse_saas.billing.providers.paymongo_provider import PayMongoBillingProvider
        from synapse_saas.billing.providers.stripe_provider import StripeBillingProvider
        from synapse_saas.billing.providers.xendit_provider import XenditBillingProvider

        assert BillingCapability.CLIENT_CONFIRM in ManualBillingProvider.supports
        for cls in (
            StripeBillingProvider,
            PaddleBillingProvider,
            PayMongoBillingProvider,
            XenditBillingProvider,
        ):
            assert BillingCapability.CLIENT_CONFIRM not in cls.supports, cls.__name__
