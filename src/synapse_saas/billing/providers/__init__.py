"""Provider registry: name → provider class. Add a provider here to expose it."""

from __future__ import annotations

from synapse_saas.billing.providers.manual_provider import ManualBillingProvider
from synapse_saas.billing.providers.paymongo_provider import PayMongoBillingProvider
from synapse_saas.billing.providers.stripe_provider import StripeBillingProvider
from synapse_saas.billing.providers.xendit_provider import XenditBillingProvider

PROVIDERS: dict[str, type] = {
    "manual": ManualBillingProvider,
    "stripe": StripeBillingProvider,
    "xendit": XenditBillingProvider,
    "paymongo": PayMongoBillingProvider,
}

__all__ = [
    "PROVIDERS",
    "ManualBillingProvider",
    "PayMongoBillingProvider",
    "StripeBillingProvider",
    "XenditBillingProvider",
]
