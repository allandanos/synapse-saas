package dev.synapse.example;

import dev.synapse.client.SynapseClient;
import dev.synapse.client.SynapseException;

import java.util.List;
import java.util.Map;

/**
 * ai-saas example — Java SDK.
 *
 * <p>A metered inference call: tokens consumed against the org's plan, quota
 * breaches as typed exceptions you can bill around.
 *
 * <p>SYNAPSE_API (default http://localhost:8000), SYNAPSE_KEY (org API key).
 */
public final class AiSaasSample {

    private static final int TOKENS_PER_CALL = 25_000;
    private static final int MAX_CALLS = 10;

    public static void main(String[] args) throws Exception {
        String api = envOr("SYNAPSE_API", "http://localhost:8000");
        String key = System.getenv("SYNAPSE_KEY");
        if (key == null || key.isBlank()) {
            System.err.println("Set SYNAPSE_KEY to an org API key");
            System.exit(1);
        }

        SynapseClient client = SynapseClient.withApiKey(api, key);

        // Where we stand
        Map<String, Object> snapshot = client.subscription.current();
        Object entitlements = snapshot.get("entitlements");
        if (entitlements instanceof Map<?, ?> e) {
            System.out.printf("plan=%s features=%s%n", e.get("plan_key"), e.get("features"));
        }

        // The metered inference call — tokens consumed atomically server-side.
        // In a real product this wraps your model invocation.
        for (int i = 1; i <= MAX_CALLS; i++) {
            try {
                client.usage.consume("ai_tokens", TOKENS_PER_CALL);
                System.out.printf("call %d: +%d tokens metered%n", i, TOKENS_PER_CALL);
            } catch (SynapseException.LimitException ex) {
                System.out.printf(
                    "call %d: quota wall — %s=%d (upgrade or bill overage)%n",
                    i, ex.metric(), ex.limit());
                return;
            }
        }

        // api_requests meters automatically on every key-authenticated call
        Map<String, Object> summary = client.usage.summary();
        if (summary.get("metrics") instanceof List<?> metrics) {
            for (Object m : metrics) {
                if (m instanceof Map<?, ?> mm) {
                    System.out.printf("  %-12s used=%s limit=%s%n",
                        mm.get("metric"), mm.get("used"), mm.get("limit"));
                }
            }
        }
    }

    private static String envOr(String key, String fallback) {
        String v = System.getenv(key);
        return v == null || v.isBlank() ? fallback : v;
    }

    private AiSaasSample() {}
}
