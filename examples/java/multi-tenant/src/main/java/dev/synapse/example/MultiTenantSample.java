package dev.synapse.example;

import dev.synapse.client.SynapseClient;

import java.util.List;
import java.util.Map;

/**
 * multi-tenant (Java) — one user, two orgs, hard isolation.
 *
 * <p>SYNAPSE_API, SYNAPSE_TOKEN (access token owning 2+ orgs).
 */
public final class MultiTenantSample {

    public static void main(String[] args) throws Exception {
        String api = envOr("SYNAPSE_API", "http://localhost:8000");
        String token = System.getenv("SYNAPSE_TOKEN");
        if (token == null || token.isBlank()) {
            System.err.println("Set SYNAPSE_TOKEN to an access token owning two orgs");
            System.exit(1);
        }

        SynapseClient me = SynapseClient.builder(api, token, null).build();
        List<Map<String, Object>> orgs =
            (List<Map<String, Object>>) (Object) List.copyOf(
                (List<?>) ((Map<String, Object>) me.auth.me()).get("orgs"));
        System.out.printf("user has %d orgs%n", orgs.size());
        if (orgs.size() < 2) {
            System.err.println("Create a second org to see isolation in action");
            System.exit(1);
        }

        String orgAId = String.valueOf(orgs.get(0).get("id"));
        String orgBId = String.valueOf(orgs.get(1).get("id"));
        SynapseClient clientA = SynapseClient.builder(api, token, null).orgId(orgAId).build();
        SynapseClient clientB = SynapseClient.builder(api, token, null).orgId(orgBId).build();

        // ── Usage is per-tenant ────────────────────────────────────────────
        clientA.usage.consume("api_requests", 100);
        Map<String, Object> summaryB = clientB.usage.summary();
        System.out.printf("org A consumed 100; org B api_requests still at %s%n",
            usedOf(summaryB));

        // ── Members are per-tenant ─────────────────────────────────────────
        int membersA = dataSize(clientA.members.list());
        int membersB = dataSize(clientB.members.list());
        System.out.printf("members — A: %d, B: %d%n", membersA, membersB);

        // ── Entitlements are per-tenant ────────────────────────────────────
        Object planA = ((Map<String, Object>) clientA.entitlements.effective()).get("plan_key");
        Object planB = ((Map<String, Object>) clientB.entitlements.effective()).get("plan_key");
        System.out.printf("plans — A: %s, B: %s%n", planA, planB);
    }

    private static Object usedOf(Map<String, Object> summary) {
        if (summary.get("metrics") instanceof List<?> metrics) {
            for (Object m : metrics) {
                if (m instanceof Map<?, ?> mm && "api_requests".equals(mm.get("metric"))) {
                    return mm.get("used");
                }
            }
        }
        return "?";
    }

    private static int dataSize(Map<String, Object> page) {
        return page.get("data") instanceof List<?> list ? list.size() : 0;
    }

    private static String envOr(String key, String fallback) {
        String v = System.getenv(key);
        return v == null || v.isBlank() ? fallback : v;
    }

    private MultiTenantSample() {}
}
