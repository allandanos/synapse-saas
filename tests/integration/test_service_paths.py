"""Remaining service paths: password reset, portal, remote plan change."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


@pytest.fixture(autouse=True)
async def _fresh_engine(clean_db):
    from synapse_saas.core.db import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


class TestPasswordReset:
    async def test_full_reset_flow(self, client: AsyncClient) -> None:
        import secrets

        await client.post(
            "/v1/auth/register",
            json={
                "email": "reset@example.com",
                "password": "password12345",
                "display_name": "R",
            },
        )
        await client.post("/v1/auth/forgot-password", json={"email": "reset@example.com"})

        from synapse_saas.core.db import get_session_factory
        from synapse_saas.identity.models import PasswordResetToken

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select

            row = (
                (
                    await session.execute(
                        select(PasswordResetToken).order_by(PasswordResetToken.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert row is not None
            user_id = row.user_id

        # Mint a plaintext token the service can hash-match (the HTTP layer only
        # logs the token in dev; we drive the same service path here)
        from datetime import UTC, datetime, timedelta

        from synapse_saas.identity.service import _hash

        token = secrets.token_urlsafe(32)
        async with factory() as session:
            session.add(
                PasswordResetToken(
                    user_id=user_id,
                    token_hash=_hash(token),
                    expires_at=datetime.now(UTC) + timedelta(minutes=30),
                )
            )
            await session.commit()

        res = await client.post(
            "/v1/auth/reset-password",
            json={"token": token, "password": "brand-new-password"},
        )
        assert res.status_code == 200, res.text

        # Old password rejected, new works
        old_login = await client.post(
            "/v1/auth/login",
            json={"email": "reset@example.com", "password": "password12345"},
        )
        assert old_login.status_code == 401
        new_login = await client.post(
            "/v1/auth/login",
            json={"email": "reset@example.com", "password": "brand-new-password"},
        )
        assert new_login.status_code == 200

    async def test_bad_reset_token_rejected(self, client: AsyncClient) -> None:
        res = await client.post(
            "/v1/auth/reset-password",
            json={"token": "n" * 50, "password": "brand-new-password"},
        )
        assert res.status_code == 401


class TestBillingPortal:
    async def test_portal_url_unsupported_for_manual(self, client: AsyncClient, org_and_tokens) -> None:
        """Manual provider has no billing portal — returns null, not an error."""
        res = await client.get("/v1/billing/portal-url", headers=org_headers(org_and_tokens))
        assert res.status_code == 200
        assert res.json()["url"] is None


class TestStripeCapabilities:
    async def test_stripe_selected_when_configured(
        self, client: AsyncClient, org_and_tokens, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from synapse_saas.billing.protocol import BillingCapability
        from synapse_saas.billing.registry import build_provider
        from synapse_saas.core.config import get_settings

        monkeypatch.setenv("SYNAPSE_STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("SYNAPSE_STRIPE_WEBHOOK_SECRET", "whsec_x")
        get_settings.cache_clear()
        provider = build_provider("stripe")
        assert BillingCapability.BILLING_PORTAL in provider.supports
        assert BillingCapability.PLAN_SYNC in provider.supports
        get_settings.cache_clear()

    async def test_unconfigured_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.billing.registry import build_provider
        from synapse_saas.core.config import get_settings
        from synapse_saas.core.errors import BillingProviderNotConfiguredError

        monkeypatch.setenv("SYNAPSE_STRIPE_SECRET_KEY", "")
        get_settings.cache_clear()
        with pytest.raises(BillingProviderNotConfiguredError):
            build_provider("stripe")
        get_settings.cache_clear()

    async def test_unknown_provider_raises(self) -> None:
        from synapse_saas.billing.registry import build_provider
        from synapse_saas.core.errors import BillingProviderNotConfiguredError

        with pytest.raises(BillingProviderNotConfiguredError):
            build_provider("alipay")


class TestUsageRollupIntegrity:
    async def test_usage_summary_endpoint_shape(self, client: AsyncClient, org_and_tokens) -> None:
        headers = org_headers(org_and_tokens)
        await client.post(
            "/v1/usage/events",
            headers=headers,
            json={"events": [{"metric": "api_requests", "quantity": 100}]},
        )
        summary = (await client.get("/v1/usage/summary", headers=headers)).json()
        assert summary["period"].endswith("-01")  # month bucket
        assert any(m["metric"] == "api_requests" and m["used"] == 100 for m in summary["metrics"])
