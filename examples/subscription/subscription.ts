/**
 * subscription example — TypeScript SDK.
 *
 * Freemium lifecycle: quota wall → trial grant → plan upgrade.
 *   SYNAPSE_API (default http://localhost:8000)
 *   SYNAPSE_TOKEN (access token for an org owner)
 */
import {
  SynapseClient,
  SynapseFeatureGatedError,
  SynapseLimitError,
} from "@synapse-saas/client";

const api = process.env.SYNAPSE_API ?? "http://localhost:8000";
const token = process.env.SYNAPSE_TOKEN;
if (!token) {
  console.error("Set SYNAPSE_TOKEN (login via the console first)");
  process.exit(1);
}

const orgId = process.env.SYNAPSE_ORG ?? "";
const client = new SynapseClient(api, { accessToken: token, orgId });

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
  await client.entitlements.grant("advanced_reports", "promo", { durationDays: 14 });
  const granted = (await client.entitlements.effective()) as { features: string[] };
  console.log(
    `after grant: advanced_reports=${granted.features.includes("advanced_reports")} (plan unchanged)`,
  );

  // ── A gated feature now passes; other gates still throw ───────────────
  try {
    await client.entitlements.grant("sso", "promo", { durationDays: 1 });
    console.log("sso granted too");
  } catch (err) {
    if (err instanceof SynapseFeatureGatedError) {
      console.log(`sso unavailable — available in: ${err.availableIn.join(", ")}`);
    }
  }

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
