package dev.synapse.example;

import dev.synapse.client.SynapseClient;
import dev.synapse.client.SynapseException;

import java.util.List;
import java.util.Map;

/**
 * hello-saas (Java) — Projects gauge through the framework API.
 *
 * <p>The client-side variant of examples/python/hello-saas: create projects
 * until the plan's cap trips (typed 402), then read the meters.
 *
 * <p>SYNAPSE_API, SYNAPSE_TOKEN (access token), SYNAPSE_ORG (org uuid).
 */
public final class HelloSaasSample {

    public static void main(String[] args) throws Exception {
        String api = envOr("SYNAPSE_API", "http://localhost:8000");
        String token = System.getenv("SYNAPSE_TOKEN");
        String orgId = System.getenv("SYNAPSE_ORG");
        if (token == null || token.isBlank()) {
            System.err.println("Set SYNAPSE_TOKEN and SYNAPSE_ORG (login via the console first)");
            System.exit(1);
        }

        SynapseClient client = SynapseClient.builder(api, token, null).orgId(orgId).build();

        // Where we stand: plan + project cap
        Map<String, Object> snapshot = client.subscription.current();
        if (snapshot.get("entitlements") instanceof Map<?, ?> ent) {
            System.out.printf("plan=%s%n", ent.get("plan_key"));
            if (ent.get("limits") instanceof Map<?, ?> limits
                    && limits.get("projects") instanceof Map<?, ?> projects) {
                System.out.printf("project cap=%s%n", projects.get("value"));
            }
        }

        // Create projects until the plan says stop
        int created = 0;
        for (int i = 1; i <= 10; i++) {
            try {
                client.usage.consume("projects", 1);
                created++;
                System.out.printf("project %d: created (+1 gauge meter)%n", i);
            } catch (SynapseException.LimitException ex) {
                System.out.printf("project %d: blocked — %s=%s (upgrade prompt)%n",
                    i, ex.metric(), ex.limit());
                break;
            }
        }

        // Meters
        if (client.usage.summary().get("metrics") instanceof List<?> metrics) {
            for (Object m : metrics) {
                if (m instanceof Map<?, ?> mm) {
                    System.out.printf("  %-12s used=%s limit=%s%n",
                        mm.get("metric"), mm.get("used"), mm.get("limit"));
                }
            }
        }
        System.out.printf("done — %d projects this run%n", created);
    }

    private static String envOr(String key, String fallback) {
        String v = System.getenv(key);
        return v == null || v.isBlank() ? fallback : v;
    }

    private HelloSaasSample() {}
}
