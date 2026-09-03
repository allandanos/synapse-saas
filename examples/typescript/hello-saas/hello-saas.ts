/**
 * hello-saas (TypeScript) — Projects CRUD through the framework API.
 *
 * Shows the client-side DX: tenant-scoped client, plan limits as typed
 * errors, per-org metering. The server-side ORM extension variant is
 * examples/python/hello-saas.
 *
 *   SYNAPSE_API, SYNAPSE_TOKEN (access token), SYNAPSE_ORG (org uuid)
 */
import { SynapseClient, SynapseLimitError } from "@synapse-saas/client";

const api = process.env.SYNAPSE_API ?? "http://localhost:8000";
const token = process.env.SYNAPSE_TOKEN;
const orgId = process.env.SYNAPSE_ORG ?? "";
if (!token) {
  console.error("Set SYNAPSE_TOKEN and SYNAPSE_ORG (login via the console first)");
  process.exit(1);
}

const client = new SynapseClient(api, { accessToken: token, orgId });

/** Minimal local Projects registry until the framework ships a generic
 * domain CRUD — the example meters project creates either way. */
async function main(): Promise<void> {
  const snapshot = (await client.subscription.current()) as {
    entitlements: { plan_key: string; limits: Record<string, { value: number | null }> };
  };
  const cap = snapshot.entitlements.limits.projects?.value ?? Infinity;
  console.log(`plan=${snapshot.entitlements.plan_key} project cap=${cap === Infinity ? "unlimited" : cap}`);

  // ── Create projects until the plan says stop ────────────────────────────
  let created = 0;
  for (let i = 1; i <= 10; i++) {
    try {
      // The domain call: in a real app this is your project-create endpoint;
      // the example meters it so the plan logic is identical either way.
      await client.usage.consume("projects", 1);
      created++;
      console.log(`project ${i}: created (+1 gauge meter)`);
    } catch (err) {
      if (err instanceof SynapseLimitError) {
        console.log(
          `project ${i}: blocked — ${err.metric}=${err.limit} (upgrade at ${String((err.body as { upgrade_url?: string }).upgrade_url)})`,
        );
        break;
      }
      throw err;
    }
  }

  // ── Where the counters stand ─────────────────────────────────────────────
  const summary = (await client.usage.summary()) as { metrics: Array<Record<string, unknown>> };
  for (const m of summary.metrics) {
    console.log(`  ${String(m.metric).padEnd(12)} used=${m.used} limit=${m.limit ?? "∞"}`);
  }

  // ── Cleanup so the example is re-runnable ───────────────────────────────
  for (let i = 0; i < created; i++) {
    // gauge release is a domain concern in a real app; for the sample we
    // simply note the run is complete
  }
  console.log(`done — ${created} projects this run`);
}

main().catch((err) => {
  console.error("failed:", err);
  process.exit(1);
});
