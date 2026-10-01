/* Liveness for the console process (container healthchecks, K8s and Cloud
 * Run probes). Deliberately independent of the API: the console keeps
 * serving with neutral branding while the API is down. */

export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
