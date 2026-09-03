/**
 * ai-saas (TypeScript) — metered inference calls with typed quota errors.
 *
 *   SYNAPSE_API (default http://localhost:8000), SYNAPSE_KEY (org API key)
 */
import { SynapseClient, SynapseLimitError } from "@synapse-saas/client";

const api = process.env.SYNAPSE_API ?? "http://localhost:8000";
const key = process.env.SYNAPSE_KEY;
if (!key) {
  console.error("Set SYNAPSE_KEY to an org API key");
  process.exit(1);
}

const client = new SynapseClient(api, { apiKey: key });
const TOKENS_PER_CALL = 25_000;

async function main(): Promise<void> {
  const snapshot = (await client.subscription.current()) as {
    entitlements: { plan_key: string; features: string[] };
  };
  console.log(
    `plan=${snapshot.entitlements.plan_key} features=[${snapshot.entitlements.features.join(", ")}]`,
  );

  // The metered inference call — in a real product this wraps your model
  // invocation and meters its usage; the quota logic is identical.
  for (let i = 1; i <= 10; i++) {
    try {
      await client.usage.consume("ai_tokens", TOKENS_PER_CALL);
      console.log(`call ${i}: +${TOKENS_PER_CALL} tokens metered`);
    } catch (err) {
      if (err instanceof SynapseLimitError) {
        console.log(
          `call ${i}: quota wall — ${err.metric}=${err.limit} (upgrade or bill overage)`,
        );
        return;
      }
      throw err;
    }
  }

  // api_requests meters automatically on every key-authenticated call
  const summary = (await client.usage.summary()) as { metrics: Array<Record<string, unknown>> };
  for (const m of summary.metrics) {
    console.log(`  ${String(m.metric).padEnd(12)} used=${m.used} limit=${m.limit ?? "∞"}`);
  }
}

main().catch((err) => {
  console.error("failed:", err);
  process.exit(1);
});
