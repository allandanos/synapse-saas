"""Billing provider factory.

Builds the configured provider from settings with a shared httpx client.
Each provider carries its own capability set; services check capabilities
rather than provider names.
"""

from __future__ import annotations

import httpx

from synapse_saas.billing.protocol import BillingProvider
from synapse_saas.billing.providers.manual_provider import ManualBillingProvider
from synapse_saas.billing.providers.paymongo_provider import PayMongoBillingProvider
from synapse_saas.billing.providers.stripe_provider import StripeBillingProvider
from synapse_saas.billing.providers.xendit_provider import XenditBillingProvider
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import BillingProviderNotConfiguredError

_shared_http: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _shared_http
    if _shared_http is None or _shared_http.is_closed:
        _shared_http = httpx.AsyncClient(timeout=30)
    return _shared_http


async def close_http_client() -> None:
    global _shared_http
    if _shared_http is not None and not _shared_http.is_closed:
        await _shared_http.aclose()
    _shared_http = None


def build_provider(name: str | None = None) -> BillingProvider:
    settings = get_settings()
    provider_name = name or settings.billing_provider
    http = get_http_client()

    match provider_name:
        case "manual":
            return ManualBillingProvider(
                webhook_token=settings.manual_webhook_token,
                currency=settings.billing_currency,
            )
        case "stripe":
            if not settings.stripe_secret_key:
                raise BillingProviderNotConfiguredError(
                    "Stripe is selected but SYNAPSE_STRIPE_SECRET_KEY is not set"
                )
            return StripeBillingProvider(
                http,
                secret_key=settings.stripe_secret_key,
                webhook_secret=settings.stripe_webhook_secret,
                currency=settings.billing_currency,
            )
        case "xendit":
            if not settings.xendit_secret_key:
                raise BillingProviderNotConfiguredError(
                    "Xendit is selected but SYNAPSE_XENDIT_SECRET_KEY is not set"
                )
            return XenditBillingProvider(
                http,
                secret_key=settings.xendit_secret_key,
                webhook_token=settings.xendit_webhook_token,
                currency=settings.billing_currency,
            )
        case "paymongo":
            if not settings.paymongo_secret_key:
                raise BillingProviderNotConfiguredError(
                    "PayMongo is selected but SYNAPSE_PAYMONGO_SECRET_KEY is not set"
                )
            return PayMongoBillingProvider(
                http,
                secret_key=settings.paymongo_secret_key,
                webhook_secret=settings.paymongo_webhook_secret,
                currency=settings.billing_currency,
            )
        case _:
            raise BillingProviderNotConfiguredError(f"Unknown billing provider {provider_name!r}")


def build_provider_by_name(name: str) -> BillingProvider:
    """For webhook ingest: build the provider the event claims to come from."""
    return build_provider(name)
