/**
 * subscription example — TypeScript SDK.
 *
 * Freemium lifecycle: quota wall → trial grant → plan upgrade.
 *   SYNAPSE_API (default http://localhost:8000)
 *   SYNAPSE_TOKEN (access token for an org owner), SYNAPSE_ORG (org uuid)
 *   SYNAPSE_PLATFORM_TOKEN (optional: platform-admin token — grants are an operator action)
 */
import { SynapseClient, SynapseLimitError } from "@synapse-saas/client";

const api = process.env.SYNAPSE_API ?? "http://localhost:8000";
const token = process.env.SYNAPSE_TOKEN;
if (!token) {
  console.error("Set SYNAPSE_TOKEN (login via the console first)");
  process.exit(1);
}

const orgId = process.env.SYNAPSE_ORG ?? "";
const client = new SynapseClient(api, { accessToken: token, orgId });
const platformToken = process.env.SYNAPSE_PLATFORM_TOKEN;

async function main(): Promise<void> {
  // ── Where we start: the free plan ──────────────────────────────────────
  const start = (await client.subscription.current()) as {
    subscription: { plan_snapshot: { key: string } };
    entitlements: { plan_key: string; features: string[] };
  };
  console.log(
    `plan=${start.entitlements.plan_key}, features=[${start.entitlements.features.join(", ")}]`,
  );

  // ── Hit the seat quota: 402 with machine-readable hints ───────────────
  try {
    for (let i = 0; i < 5; i++) {
      await client.members.invite(`seat-${i}@example.com`);
    }
  } catch (err) {
    if (err instanceof SynapseLimitError) {
      console.log(
        `quota wall: ${err.metric}=${err.limit} → upgrade at ${String((err.body as { upgrade_url?: string }).upgrade_url)}`,
      );
    } else {
      throw err;
    }
  }

  // ── Trial grant: a paid feature without a plan change ──────────────────
  // Grants are an OPERATOR action: a tenant can never grant itself features.
  // The platform team does this with a platform-admin token against the org.
  if (platformToken) {
    const operator = new SynapseClient(api, { accessToken: platformToken });
    await operator.entitlements.grant(orgId, "advanced_reports", "promo", { durationDays: 14 });
    const granted = (await client.entitlements.effective()) as { features: string[] };
    console.log(
      `after grant: advanced_reports=${granted.features.includes("advanced_reports")} (plan unchanged)`,
    );
  } else {
    console.log("skipping trial grant (set SYNAPSE_PLATFORM_TOKEN — grants are an operator action)");
  }

  // ── Other gates still hold: sso is enterprise-only ─────────────────────
  // A gated route answers 403 with `feature` + `available_in`; the SDK maps
  // that to SynapseFeatureGatedError so the UI can render an upgrade prompt.
  const gated = (await client.entitlements.effective()) as { features: string[] };
  console.log(`sso available: ${gated.features.includes("sso")} (enterprise plan or an operator grant)`);

  // ── Plan upgrade: the cap moves ────────────────────────────────────────
  await client.subscription.change("starter");
  const after = (await client.subscription.current()) as {
    entitlements: { plan_key: string };
  };
  console.log(`after upgrade: plan=${after.entitlements.plan_key}, seats=10 — invites pass now`);
}

main().catch((err) => {
  console.error("failed:", err);
  process.exit(1);
});
