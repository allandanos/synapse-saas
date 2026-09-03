"""ai-saas (Python) — metering an AI product.

The SynapseDev.AI shape: every inference call meters ai_tokens against the
org's plan; quota breaches arrive as typed errors you can bill around.

    SYNAPSE_API (default http://localhost:8000)
    SYNAPSE_KEY (an API key for the org — console → API keys)
"""

from __future__ import annotations

import os
import sys

from synapse_saas_client import SynapseClient, SynapseLimitError

API = os.environ.get("SYNAPSE_API", "http://localhost:8000")
KEY = os.environ.get("SYNAPSE_KEY", "")

if not KEY:
    sys.exit("Set SYNAPSE_KEY to an org API key")

TOKENS_PER_CALL = 25_000
MAX_CALLS = 10


def main() -> None:
    client = SynapseClient(API, api_key=KEY)

    # Where we stand: current quota + entitlements in one call
    snapshot = client.subscription.current()
    entitlements = snapshot["entitlements"]
    print(f"plan={entitlements['plan_key']} features={entitlements['features']}")

    # The metered inference call — in a real product this wraps your model
    # invocation and meters its usage; the quota logic is identical.
    for i in range(1, MAX_CALLS + 1):
        try:
            client.usage.consume("ai_tokens", TOKENS_PER_CALL)
            print(f"call {i}: +{TOKENS_PER_CALL} tokens metered")
        except SynapseLimitError as err:
            print(f"call {i}: quota wall — {err.metric}={err.limit} (upgrade or bill overage)")
            return

    # api_requests meters automatically on every key-authenticated call
    summary = client.usage.summary()
    for m in summary["metrics"]:
        limit = m["limit"] if m["limit"] is not None else "∞"
        print(f"  {m['metric']:<12} used={m['used']} limit={limit}")


if __name__ == "__main__":
    main()
