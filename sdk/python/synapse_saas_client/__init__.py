"""Python client SDK for the Synapse SaaS Framework API.

Two credential modes:
- API key (`sk_…`): programmatic org access — org is pinned server-side
- Access token: user session from the console login flow

    from synapse_saas_client import SynapseClient

    client = SynapseClient("https://api.example.com", api_key="sk_…")
    usage = client.usage.summary()
    for m in usage["metrics"]:
        print(m["metric"], m["used"], "/", m["limit"])
"""

from synapse_saas_client.client import SynapseClient
from synapse_saas_client.errors import (
    SynapseAuthError,
    SynapseError,
    SynapseFeatureGatedError,
    SynapseLimitError,
    SynapseNotFoundError,
)

__all__ = [
    "SynapseAuthError",
    "SynapseClient",
    "SynapseError",
    "SynapseFeatureGatedError",
    "SynapseLimitError",
    "SynapseNotFoundError",
]
