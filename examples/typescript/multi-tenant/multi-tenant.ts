/**
 * multi-tenant (TypeScript) — one user, two orgs, hard isolation.
 *
 *   SYNAPSE_API, SYNAPSE_TOKEN (access token owning 2+ orgs)
 */
import { SynapseClient } from "@synapse-saas/client";

const api = process.env.SYNAPSE_API ?? "http://localhost:8000";
const token = process.env.SYNAPSE_TOKEN;
if (!token) {
  console.error("Set SYNAPSE_TOKEN to an access token owning two orgs");
  process.exit(1);
}

function used(metrics: Array<{ metric: string; used: number }>, key: string): number {
  return metrics.find((m) => m.metric === key)?.used ?? 0;
}

async function main(): Promise<void> {
  const me = new SynapseClient(api, { accessToken: token });
  const orgs = ((await me.auth.me()) as { orgs: Array<{ id: string; slug: string }> }).orgs;
  console.log(`user has ${orgs.length} orgs: ${orgs.map((o) => o.slug).join(", ")}`);
  if (orgs.length < 2) {
    console.error("Create a second org for this user to see isolation in action");
    process.exit(1);
  }

  const [orgA, orgB] = orgs;
  const clientA = new SynapseClient(api, { accessToken: token, orgId: orgA.id });
  const clientB = new SynapseClient(api, { accessToken: token, orgId: orgB.id });

  // ── Usage is per-tenant ────────────────────────────────────────────────
  await clientA.usage.consume("api_requests", 100);
  const summaryB = (await clientB.usage.summary()) as { metrics: [] };
  console.log(`org A consumed 100; org B still at ${used(summaryB.metrics, "api_requests")}`);

  // ── Members are per-tenant ─────────────────────────────────────────────
  const membersA = ((await clientA.members.list()) as { data: unknown[] }).data.length;
  const membersB = ((await clientB.members.list()) as { data: unknown[] }).data.length;
  console.log(`members — A: ${membersA}, B: ${membersB}`);

  // ── Entitlements are per-tenant ────────────────────────────────────────
  const entA = (await clientA.entitlements.effective()) as { plan_key: string };
  const entB = (await clientB.entitlements.effective()) as { plan_key: string };
  console.log(`plans — A: ${entA.plan_key}, B: ${entB.plan_key}`);
}

main().catch((err) => {
  console.error("failed:", err);
  process.exit(1);
});
