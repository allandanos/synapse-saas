package dev.synapse.client;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Java client for the Synapse SaaS Framework API.
 *
 * <p>Two credential modes: API key ({@code sk_…}, org pinned server-side) or
 * an access token from the console login flow. Uses the JDK HttpClient —
 * no external HTTP dependency. Thread-safe.
 */
public class SynapseClient {

    private final String baseUrl;
    private final String authHeader;
    private final String orgId;
    private final HttpClient http;
    private final ObjectMapper mapper = new ObjectMapper();

    public final Auth auth = new Auth();
    public final Orgs orgs = new Orgs();
    public final Members members = new Members();
    public final Subscription subscription = new Subscription();
    public final Usage usage = new Usage();
    public final Entitlements entitlements = new Entitlements();
    public final ApiKeys apiKeys = new ApiKeys();

    private SynapseClient(Builder b) {
        this.baseUrl = trimSlash(b.baseUrl);
        this.authHeader = "Bearer " + (b.apiKey != null ? b.apiKey : b.accessToken);
        this.orgId = b.orgId;
        this.http = b.httpClient != null ? b.httpClient
            : HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(30)).build();
    }

    public static Builder builder(String baseUrl, String apiKey, String accessToken) {
        return new Builder(baseUrl, apiKey, accessToken);
    }

    /** Convenience: API-key client. */
    public static SynapseClient withApiKey(String baseUrl, String apiKey) {
        return builder(baseUrl, apiKey, null).build();
    }

    public static final class Builder {
        private final String baseUrl;
        private final String apiKey;
        private final String accessToken;
        private String orgId;
        private HttpClient httpClient;

        private Builder(String baseUrl, String apiKey, String accessToken) {
            if (apiKey == null && accessToken == null) {
                throw new IllegalArgumentException("apiKey or accessToken is required");
            }
            this.baseUrl = baseUrl;
            this.apiKey = apiKey;
            this.accessToken = accessToken;
        }

        public Builder orgId(String orgId) { this.orgId = orgId; return this; }

        /** Test seam: inject a custom HttpClient (route through a stub). */
        public Builder httpClient(HttpClient client) { this.httpClient = client; return this; }

        public SynapseClient build() { return new SynapseClient(this); }
    }

    // ── resource namespaces ───────────────────────────────────────────────────

    public final class Auth {
        public Map<String, Object> me() throws IOException, InterruptedException {
            return call("GET", "/v1/auth/me", null, null);
        }
    }

    public final class Orgs {
        public Map<String, Object> list() throws IOException, InterruptedException {
            return call("GET", "/v1/orgs", null, null);
        }

        public Map<String, Object> create(String name) throws IOException, InterruptedException {
            return call("POST", "/v1/orgs", Map.of("name", name), null);
        }

        public Map<String, Object> current() throws IOException, InterruptedException {
            return call("GET", "/v1/orgs/current", null, null);
        }
    }

    public final class Members {
        public Map<String, Object> list() throws IOException, InterruptedException {
            return call("GET", "/v1/orgs/current/members", null, null);
        }

        public Map<String, Object> invite(String email) throws IOException, InterruptedException {
            return call("POST", "/v1/orgs/current/members/invite",
                Map.of("email", email, "role_keys", List.of("member")), null);
        }

        public void remove(String membershipId) throws IOException, InterruptedException {
            call("DELETE", "/v1/memberships/" + membershipId, null, null);
        }
    }

    public final class Subscription {
        /** Subscription + entitlements + usage snapshot in one call. */
        public Map<String, Object> current() throws IOException, InterruptedException {
            return call("GET", "/v1/subscription", null, null);
        }

        public List<Map<String, Object>> plans() throws IOException, InterruptedException {
            return callList("GET", "/v1/plans", null);
        }

        public Map<String, Object> change(String planKey) throws IOException, InterruptedException {
            return call("POST", "/v1/subscription/change", Map.of("plan_key", planKey), null);
        }

        public Map<String, Object> startTrial(String planKey) throws IOException, InterruptedException {
            return call("POST", "/v1/subscription/trial", Map.of("plan_key", planKey), null);
        }

        public Map<String, Object> cancel(boolean atPeriodEnd) throws IOException, InterruptedException {
            return call("POST", "/v1/subscription/cancel", Map.of("at_period_end", atPeriodEnd), null);
        }
    }

    public final class Usage {
        public Map<String, Object> summary() throws IOException, InterruptedException {
            return call("GET", "/v1/usage/summary", null, null);
        }

        /** Meter + enforce: throws LimitException (402) when the quota trips. */
        public Map<String, Object> consume(String metric, int quantity)
                throws IOException, InterruptedException {
            return call("POST", "/v1/usage/consume",
                Map.of("events", List.of(Map.of("metric", metric, "quantity", quantity))), null);
        }
    }

    public final class Entitlements {
        public Map<String, Object> effective() throws IOException, InterruptedException {
            return call("GET", "/v1/entitlements", null, null);
        }
    }

    public final class ApiKeys {
        /** Returns the plaintext key exactly once — persist it immediately. */
        public Map<String, Object> create(String name) throws IOException, InterruptedException {
            return call("POST", "/v1/api-keys",
                Map.of("name", name, "scopes", List.of()), null);
        }

        public void revoke(String keyId) throws IOException, InterruptedException {
            call("DELETE", "/v1/api-keys/" + keyId, null, null);
        }
    }

    // ── request core ──────────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> call(String method, String path, Object body,
                                     Map<String, String> params)
            throws IOException, InterruptedException {
        String uri = baseUrl + path;
        HttpRequest.Builder req = HttpRequest.newBuilder(URI.create(uri))
            .header("Authorization", authHeader);
        if (orgId != null) req.header("X-Org-Id", orgId);

        if (body != null) {
            req.method(method, HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
               .header("Content-Type", "application/json");
        } else {
            req.method(method, HttpRequest.BodyPublishers.noBody());
        }

        HttpResponse<String> resp = http.send(req.build(), HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() == 204) return null;
        Map<String, Object> parsed = mapper.readValue(resp.body(), Map.class);
        if (resp.statusCode() >= 400) {
            throw SynapseException.forStatus(resp.statusCode(), parsed);
        }
        return parsed;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> callList(String method, String path, Object body)
            throws IOException, InterruptedException {
        HttpResponse<String> resp = send(method, path, body);
        return mapper.readValue(resp.body(), List.class);
    }

    private HttpResponse<String> send(String method, String path, Object body)
            throws IOException, InterruptedException {
        HttpRequest.Builder req = HttpRequest.newBuilder(URI.create(baseUrl + path))
            .header("Authorization", authHeader)
            .method(method, body != null
                ? HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))
                : HttpRequest.BodyPublishers.noBody());
        if (body != null) req.header("Content-Type", "application/json");
        return http.send(req.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static String trimSlash(String s) {
        String out = s;
        while (out.endsWith("/")) out = out.substring(0, out.length() - 1);
        return out;
    }
}
