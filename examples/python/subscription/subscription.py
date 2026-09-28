"""subscription (Python) — freemium lifecycle: quota wall → trial grant → upgrade.

SYNAPSE_API (default http://localhost:8000)
SYNAPSE_TOKEN (access token for an org owner), SYNAPSE_ORG (org uuid)
SYNAPSE_PLATFORM_TOKEN (optional: platform-admin token — grants are an operator action)
"""

from __future__ import annotations

import os
import sys

from synapse_saas_client import SynapseClient, SynapseLimitError

API = os.environ.get("SYNAPSE_API", "http://localhost:8000")
TOKEN = os.environ.get("SYNAPSE_TOKEN", "")
ORG = os.environ.get("SYNAPSE_ORG", "")
PLATFORM_TOKEN = os.environ.get("SYNAPSE_PLATFORM_TOKEN", "")

if not TOKEN:
    sys.exit("Set SYNAPSE_TOKEN and SYNAPSE_ORG (login via the console first)")


def main() -> None:
    client = SynapseClient(API, access_token=TOKEN, org_id=ORG)

    # ── Where we start: the free plan ──────────────────────────────────────
    start = client.subscription.current()
    entitlements = start["entitlements"]
    print(f"plan: {entitlements['plan_key']}, features: {entitlements['features']}")

    # ── Hit the seat quota: typed 402 with hints ──────────────────────────
    for i in range(5):
        try:
            client.members.invite(f"seat-{i}@example.com")
        except SynapseLimitError as err:
            print(f"quota wall: {err.metric}={err.limit} → upgrade at {err.body.get('upgrade_url')}")
            break

    # ── Trial grant: a paid feature without a plan change ─────────────────
    # Grants are an OPERATOR action: a tenant can never grant itself features.
    # The platform team does this with a platform-admin token against the org.
    if PLATFORM_TOKEN:
        operator = SynapseClient(API, access_token=PLATFORM_TOKEN)
        operator.entitlements.grant(ORG, "advanced_reports", "promo", duration_days=14)
        granted = client.entitlements.effective()
        print(
            f"after grant: advanced_reports={'advanced_reports' in granted['features']} "
            f"(plan unchanged: {granted['plan_key']})"
        )
    else:
        print("skipping trial grant (set SYNAPSE_PLATFORM_TOKEN — grants are an operator action)")

    # ── Plan upgrade: the cap moves ────────────────────────────────────────
    client.subscription.change("starter")
    after = client.subscription.current()
    print(f"after upgrade: plan={after['entitlements']['plan_key']}, seats=10 — invites pass now")


if __name__ == "__main__":
    main()
