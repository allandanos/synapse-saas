"""multi-tenant example — Python SDK.

One user, two orgs, hard isolation. Expects the compose stack running and:
    SYNAPSE_API (default http://localhost:8000)
    SYNAPSE_TOKEN (an access token for a user owning two orgs)
"""

from __future__ import annotations

import os
import sys

from synapse_saas_client import SynapseClient, SynapseNotFoundError

API = os.environ.get("SYNAPSE_API", "http://localhost:8000")
TOKEN = os.environ.get("SYNAPSE_TOKEN", "")

if not TOKEN:
    sys.exit("Set SYNAPSE_TOKEN to an access token (login via the console first)")


def main() -> None:
    # Un-scoped client: sees both orgs
    me = SynapseClient(API, access_token=TOKEN)
    orgs = me.auth.me()["orgs"]
    print(f"user has {len(orgs)} orgs: {[o['slug'] for o in orgs]}")
    if len(orgs) < 2:
        sys.exit("Create a second org for this user to see isolation in action")

    org_a, org_b = orgs[0], orgs[1]

    # Org-scoped clients: same user, different tenants
    client_a = SynapseClient(API, access_token=TOKEN, org_id=org_a["id"])
    client_b = SynapseClient(API, access_token=TOKEN, org_id=org_b["id"])

    # ── Usage is per-tenant ────────────────────────────────────────────────
    a_before = client_a.usage.summary()["metrics"]
    client_a.usage.consume("api_requests", 100)["total"]
    b_after = client_b.usage.summary()["metrics"]

    def used(metrics: list, metric: str = "api_requests") -> int:
        return next((m["used"] for m in metrics if m["metric"] == metric), 0)

    print(f"org A consumed 100 → A used={used(a_before)}→+100; B still {used(b_after)}")

    # ── Members are per-tenant ─────────────────────────────────────────────
    members_a = client_a.members.list()["data"]
    members_b = client_b.members.list()["data"]
    print(f"members — A: {len(members_a)}, B: {len(members_b)} (invites count per org)")

    # ── Entitlements are per-tenant ────────────────────────────────────────
    ent_a = client_a.entitlements.effective()
    ent_b = client_b.entitlements.effective()
    print(f"plans — A: {ent_a['plan_key']}, B: {ent_b['plan_key']}")

    # ── Cross-tenant access is a clean 404 ────────────────────────────────
    # A's client asking for a B membership id: not-found, no existence leak.
    if members_b:
        try:
            # route is org-scoped to A; B's id resolves to nothing
            client_a._http.get(f"/v1/memberships/{members_b[0]['id']}")
        except SynapseNotFoundError:
            print("cross-tenant membership lookup → 404 (as designed)")


if __name__ == "__main__":
    main()
