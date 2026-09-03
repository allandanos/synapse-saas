package dev.synapse.example;

import dev.synapse.client.SynapseClient;
import dev.synapse.client.SynapseException;

import java.util.List;
import java.util.Map;

/**
 * subscription (Java) — freemium lifecycle: quota wall → trial grant → upgrade.
 *
 * <p>SYNAPSE_API, SYNAPSE_TOKEN (access token for an org owner),
 * SYNAPSE_ORG (org uuid).
 */
public final class SubscriptionSample {

    public static void main(String[] args) throws Exception {
        String api = envOr("SYNAPSE_API", "http://localhost:8000");
        String token = System.getenv("SYNAPSE_TOKEN");
        if (token == null || token.isBlank()) {
            System.err.println("Set SYNAPSE_TOKEN and SYNAPSE_ORG (login via the console first)");
            System.exit(1);
        }
        String orgId = System.getenv("SYNAPSE_ORG");
        SynapseClient client = SynapseClient.builder(api, token, null).orgId(orgId).build();

        // ── Where we start: the free plan ──────────────────────────────────
        printPlan(client.subscription.current(), "plan");

        // ── Hit the seat quota: typed 402 with hints ───────────────────────
        for (int i = 0; i < 5; i++) {
            try {
                client.members.invite("seat-" + i + "@example.com");
            } catch (SynapseException.LimitException ex) {
                System.out.printf("quota wall: %s=%d → upgrade at %s%n",
                    ex.metric(), ex.limit(), ex.getBody().get("upgrade_url"));
                break;
            }
        }

        // ── Trial grant: a paid feature without a plan change ──────────────
        client.entitlements.grant("advanced_reports", "promo", 14);
        Map<String, Object> granted = client.entitlements.effective();
        if (granted.get("features") instanceof List<?> features) {
            System.out.printf("after grant: advanced_reports=%s (plan unchanged)%n",
                features.contains("advanced_reports"));
        }

        // ── Plan upgrade: the cap moves ────────────────────────────────────
        client.subscription.change("starter");
        printPlan(client.subscription.current(), "after upgrade");
        System.out.println("seats=10 — invites pass now");
    }

    private static void printPlan(Map<String, Object> snapshot, String prefix) {
        if (snapshot.get("entitlements") instanceof Map<?, ?> ent) {
            System.out.printf("%s: plan=%s features=%s%n", prefix, ent.get("plan_key"), ent.get("features"));
        }
    }

    private static String envOr(String key, String fallback) {
        String v = System.getenv(key);
        return v == null || v.isBlank() ? fallback : v;
    }

    private SubscriptionSample() {}
}
