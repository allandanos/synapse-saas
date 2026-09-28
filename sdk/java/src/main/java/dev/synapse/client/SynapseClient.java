package dev.synapse.client;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.StringJoiner;
import java.util.UUID;

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
    public final Roles roles = new Roles();
    public final Billing billing = new Billing();
    public final Invoices invoices = new Invoices();
    public final Webhooks webhooks = new Webhooks();
    public final Files files = new Files();
    public final FeatureFlags featureFlags = new FeatureFlags();
    public final Agents agents = new Agents();
    public final Audit audit = new Audit();
    public final Admin admin = new Admin();

    /** One page of a list route: the items plus the server's total ({@code X-Total-Count}). */
    public record Page(List<Map<String, Object>> items, int total, int limit, int offset) {}

    /** Framework version, active billing/identity providers, tenant isolation mode. */
    public Map<String, Object> meta() throws IOException, InterruptedException {
        return call("GET", "/v1/meta", null, null);
    }

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
        public Map<String, Object> register(String email, String password, String displayName)
                throws IOException, InterruptedException {
            return call("POST", "/v1/auth/register",
                Map.of("email", email, "password", password, "display_name", displayName), null);
        }

        /** {@code {user, tokens}}; SSO-only accounts answer 401 with {@code sso_url}. */
        public Map<String, Object> login(String email, String password) throws IOException, InterruptedException {
            return call("POST", "/v1/auth/login", Map.of("email", email, "password", password), null);
        }

        public Map<String, Object> refresh(String refreshToken) throws IOException, InterruptedException {
            return call("POST", "/v1/auth/refresh", Map.of("refresh_token", refreshToken), null);
        }

        public void logout() throws IOException, InterruptedException {
            call("POST", "/v1/auth/logout", null, null);
        }

        public void forgotPassword(String email) throws IOException, InterruptedException {
            call("POST", "/v1/auth/forgot-password", Map.of("email", email), null);
        }

        public Map<String, Object> resetPassword(String token, String password)
                throws IOException, InterruptedException {
            return call("POST", "/v1/auth/reset-password", Map.of("token", token, "password", password), null);
        }

        public Map<String, Object> acceptInvite(String token) throws IOException, InterruptedException {
            return call("POST", "/v1/auth/accept-invite", Map.of("token", token), null);
        }

        /** Pin an org for later requests without {@code X-Org-Id} (the new token carries the claim). */
        public void switchOrg(String organizationId) throws IOException, InterruptedException {
            call("POST", "/v1/auth/switch-org", Map.of("organization_id", organizationId), null);
        }

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

        /** Patch the current org: {@code name} and/or {@code settings}. */
        public Map<String, Object> update(Map<String, Object> patch) throws IOException, InterruptedException {
            return call("PATCH", "/v1/orgs/current", patch, null);
        }
    }

    public final class Members {
        /** Patch a membership: {@code role_keys} and/or {@code status} (active|suspended). */
        public Map<String, Object> update(String membershipId, Map<String, Object> patch)
                throws IOException, InterruptedException {
            return call("PATCH", "/v1/memberships/" + membershipId, patch, null);
        }

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
        public Map<String, Object> resume() throws IOException, InterruptedException {
            return call("POST", "/v1/subscription/resume", null, null);
        }

        public Page plansPage(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/plans", limit, offset, null);
        }

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
        /** Read-only pre-flight: {@code {metric, used, limit, remaining, within_limit, …}}. */
        public Map<String, Object> check(String metric, int quantity) throws IOException, InterruptedException {
            return call("GET", "/v1/usage/check", null,
                Map.of("metric", metric, "quantity", String.valueOf(quantity)));
        }

        /** Meter without enforcing (never blocks). {@code idempotency_key} per event dedupes retries. */
        public List<Map<String, Object>> record(List<Map<String, Object>> events)
                throws IOException, InterruptedException {
            return callList("POST", "/v1/usage/events", Map.of("events", events));
        }

        public Map<String, Object> summary() throws IOException, InterruptedException {
            return call("GET", "/v1/usage/summary", null, null);
        }

        /** Meter + enforce: throws LimitException (402) when the quota trips. */
        public Map<String, Object> consume(String metric, int quantity)
                throws IOException, InterruptedException {
            return call("POST", "/v1/usage/consume",
                Map.of("events", List.of(Map.of("metric", metric, "quantity", quantity))), null);
        }

        /** All-or-nothing batch: the first breach throws LimitException and nothing is counted. */
        public List<Map<String, Object>> consumeBatch(List<Map<String, Object>> events)
                throws IOException, InterruptedException {
            return callList("POST", "/v1/usage/consume-batch", Map.of("events", events));
        }

        /** Gauges are levels (seats, projects, bytes stored): set the absolute value. */
        public Map<String, Object> setGauge(String metric, long value)
                throws IOException, InterruptedException {
            return call("POST", "/v1/usage/gauge", Map.of("metric", metric, "value", value), null);
        }

        /** Move a gauge by delta (never below zero). */
        public Map<String, Object> adjustGauge(String metric, long delta)
                throws IOException, InterruptedException {
            return call("POST", "/v1/usage/gauge", Map.of("metric", metric, "delta", delta), null);
        }
    }

    public final class Entitlements {
        public Map<String, Object> effective() throws IOException, InterruptedException {
            return call("GET", "/v1/entitlements", null, null);
        }

        /** Platform-operator action (platform-admin bearer): time-boxed feature grant for any org. */
        public Map<String, Object> grant(String organizationId, String featureKey, String source, int durationDays)
                throws IOException, InterruptedException {
            return call("POST", "/v1/admin/orgs/" + organizationId + "/entitlements/grants",
                Map.of("feature_key", featureKey, "source", source, "duration_days", durationDays),
                null);
        }
    }

    public final class ApiKeys {
        /** Pages the org's keys (never the secrets: those are shown once at {@link #create}). */
        public Page list(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/api-keys", limit, offset, null);
        }

        /** Returns the plaintext key exactly once — persist it immediately. */
        public Map<String, Object> create(String name) throws IOException, InterruptedException {
            return call("POST", "/v1/api-keys",
                Map.of("name", name, "scopes", List.of()), null);
        }

        public void revoke(String keyId) throws IOException, InterruptedException {
            call("DELETE", "/v1/api-keys/" + keyId, null, null);
        }
    }

    public final class Roles {
        public List<Map<String, Object>> list() throws IOException, InterruptedException {
            return callList("GET", "/v1/roles", null);
        }

        /** The permission catalog ({@code resource:action} keys). */
        public List<Map<String, Object>> permissions() throws IOException, InterruptedException {
            return callList("GET", "/v1/permissions", null);
        }

        public Map<String, Object> create(String key, String name, List<String> permissions)
                throws IOException, InterruptedException {
            return call("POST", "/v1/roles", Map.of("key", key, "name", name, "permissions", permissions), null);
        }

        public Map<String, Object> update(String roleId, Map<String, Object> patch)
                throws IOException, InterruptedException {
            return call("PATCH", "/v1/roles/" + roleId, patch, null);
        }

        public void delete(String roleId) throws IOException, InterruptedException {
            call("DELETE", "/v1/roles/" + roleId, null, null);
        }
    }

    public final class Billing {
        /** {@code {url}} for hosted providers, or manual payment instructions. */
        public Map<String, Object> checkout(String planKey) throws IOException, InterruptedException {
            return call("POST", "/v1/billing/checkout", Map.of("plan_key", planKey), null);
        }

        /** Manual provider only (409 {@code checkout_confirm_not_allowed} elsewhere). */
        public Map<String, Object> confirmCheckout(String planKey) throws IOException, InterruptedException {
            return call("POST", "/v1/billing/checkout/confirm", Map.of("plan_key", planKey), null);
        }

        public Map<String, Object> portalUrl() throws IOException, InterruptedException {
            return call("GET", "/v1/billing/portal-url", null, null);
        }

        public Map<String, Object> spendSummary() throws IOException, InterruptedException {
            return call("GET", "/v1/billing/spend-summary", null, null);
        }

        public List<Map<String, Object>> spendMonthly() throws IOException, InterruptedException {
            return callList("GET", "/v1/billing/spend-monthly", null);
        }
    }

    public final class Invoices {
        public Page list(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/billing/invoices", limit, offset, null);
        }

        public Map<String, Object> get(String invoiceId) throws IOException, InterruptedException {
            return call("GET", "/v1/billing/invoices/" + invoiceId, null, null);
        }

        /** The framework-rendered invoice PDF. */
        public byte[] pdf(String invoiceId) throws IOException, InterruptedException {
            return callBytes("/v1/billing/invoices/" + invoiceId + "/pdf");
        }

        /** Draft (or return) the period invoice; {@code period} is {@code YYYY-MM} or null for the current one. */
        public Map<String, Object> draft(String period) throws IOException, InterruptedException {
            Map<String, Object> body = new HashMap<>();
            if (period != null) body.put("period", period);
            return call("POST", "/v1/billing/invoices/draft", body, null);
        }

        public Map<String, Object> finalize(String invoiceId) throws IOException, InterruptedException {
            return call("POST", "/v1/billing/invoices/" + invoiceId + "/finalize", null, null);
        }
    }

    public final class Webhooks {
        public Page listEndpoints(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/webhooks/endpoints", limit, offset, null);
        }

        /** The signing {@code secret} is returned exactly once. Empty {@code events} means every public event. */
        public Map<String, Object> createEndpoint(String url, List<String> events)
                throws IOException, InterruptedException {
            return call("POST", "/v1/webhooks/endpoints",
                Map.of("url", url, "events", events == null ? List.of() : events), null);
        }

        public void deleteEndpoint(String endpointId) throws IOException, InterruptedException {
            call("DELETE", "/v1/webhooks/endpoints/" + endpointId, null, null);
        }

        public Page listDeliveries(Integer limit, Integer offset, String endpointId)
                throws IOException, InterruptedException {
            Map<String, String> extra = new HashMap<>();
            if (endpointId != null) extra.put("endpoint_id", endpointId);
            return callPage("/v1/webhooks/deliveries", limit, offset, extra);
        }

        public Map<String, Object> retryDelivery(String deliveryId) throws IOException, InterruptedException {
            return call("POST", "/v1/webhooks/deliveries/" + deliveryId + "/retry", null, null);
        }
    }

    public final class Files {
        public Page list(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/files", limit, offset, null);
        }

        /** Direct multipart upload (≤10 MiB). Larger objects: {@link #presignUpload} + {@link #complete}. */
        public Map<String, Object> upload(String name, byte[] content, String contentType)
                throws IOException, InterruptedException {
            String boundary = "----synapse" + UUID.randomUUID();
            String type = contentType == null ? "application/octet-stream" : contentType;
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            out.write(("--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"file\"; filename=\"" + name + "\"\r\n"
                + "Content-Type: " + type + "\r\n\r\n").getBytes(StandardCharsets.UTF_8));
            out.write(content);
            out.write(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
            HttpResponse<byte[]> resp = send("POST", "/v1/files", null, null,
                HttpRequest.BodyPublishers.ofByteArray(out.toByteArray()),
                "multipart/form-data; boundary=" + boundary);
            return parseMap(resp);
        }

        public byte[] download(String fileId) throws IOException, InterruptedException {
            return callBytes("/v1/files/" + fileId);
        }

        public Map<String, Object> presignDownload(String fileId) throws IOException, InterruptedException {
            return call("POST", "/v1/files/" + fileId + "/presign", null, null);
        }

        /** {@code {id, url, method, headers, expires_in}}: PUT the bytes there, then {@link #complete}. */
        public Map<String, Object> presignUpload(String name, long sizeBytes, String contentType)
                throws IOException, InterruptedException {
            return call("POST", "/v1/files/presign-upload", Map.of(
                "name", name, "size_bytes", sizeBytes,
                "content_type", contentType == null ? "application/octet-stream" : contentType), null);
        }

        public Map<String, Object> complete(String fileId) throws IOException, InterruptedException {
            return call("POST", "/v1/files/" + fileId + "/complete", null, null);
        }

        public void delete(String fileId) throws IOException, InterruptedException {
            call("DELETE", "/v1/files/" + fileId, null, null);
        }
    }

    public final class FeatureFlags {
        /** {@code {key, enabled}} for the caller's org + user (overrides + rollout aware). */
        public Map<String, Object> check(String key) throws IOException, InterruptedException {
            return call("GET", "/v1/feature-flags/check/" + key, null, null);
        }

        // Platform-admin surface
        public Page list(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/feature-flags", limit, offset, null);
        }

        public Map<String, Object> create(Map<String, Object> body) throws IOException, InterruptedException {
            return call("POST", "/v1/feature-flags", body, null);
        }

        public Map<String, Object> update(String key, Map<String, Object> patch)
                throws IOException, InterruptedException {
            return call("PATCH", "/v1/feature-flags/" + key, patch, null);
        }

        public List<Map<String, Object>> listOverrides(String key) throws IOException, InterruptedException {
            return callList("GET", "/v1/feature-flags/" + key + "/overrides", null);
        }

        public Map<String, Object> setOverride(String key, Map<String, Object> body)
                throws IOException, InterruptedException {
            return call("POST", "/v1/feature-flags/" + key + "/overrides", body, null);
        }

        public void deleteOverride(String overrideId) throws IOException, InterruptedException {
            call("DELETE", "/v1/feature-flags/overrides/" + overrideId, null, null);
        }
    }

    /** Registry + governance (ADR 0007); every call is behind the {@code agents} feature. */
    public final class Agents {
        public Page list(Integer limit, Integer offset) throws IOException, InterruptedException {
            return callPage("/v1/agents", limit, offset, null);
        }

        public Map<String, Object> create(String slug, String name, Map<String, Object> config)
                throws IOException, InterruptedException {
            return call("POST", "/v1/agents",
                Map.of("slug", slug, "name", name, "config", config == null ? Map.of() : config), null);
        }

        public Map<String, Object> get(String agentId) throws IOException, InterruptedException {
            return call("GET", "/v1/agents/" + agentId, null, null);
        }

        public Map<String, Object> update(String agentId, Map<String, Object> patch)
                throws IOException, InterruptedException {
            return call("PATCH", "/v1/agents/" + agentId, patch, null);
        }

        public void delete(String agentId) throws IOException, InterruptedException {
            call("DELETE", "/v1/agents/" + agentId, null, null);
        }

        public Map<String, Object> enable(String agentId) throws IOException, InterruptedException {
            return call("POST", "/v1/agents/" + agentId + "/enable", null, null);
        }

        public Map<String, Object> disable(String agentId) throws IOException, InterruptedException {
            return call("POST", "/v1/agents/" + agentId + "/disable", null, null);
        }
    }

    public final class Audit {
        public Map<String, Object> list(Integer limit, Integer offset, Map<String, String> filters)
                throws IOException, InterruptedException {
            return call("GET", "/v1/audit", null, paging(limit, offset, filters));
        }
    }

    /** Platform-operator surface (platform-admin bearer, explicit org ids) — ADR 0008. */
    public final class Admin {
        public Map<String, Object> entitlements(String organizationId) throws IOException, InterruptedException {
            return call("GET", "/v1/admin/orgs/" + organizationId + "/entitlements", null, null);
        }

        public Map<String, Object> grant(String organizationId, Map<String, Object> body)
                throws IOException, InterruptedException {
            return call("POST", "/v1/admin/orgs/" + organizationId + "/entitlements/grants", body, null);
        }

        public void revokeGrant(String organizationId, String grantId) throws IOException, InterruptedException {
            call("DELETE", "/v1/admin/orgs/" + organizationId + "/entitlements/grants/" + grantId, null, null);
        }

        public Map<String, Object> payInvoice(String invoiceId, long amountCents, String reference)
                throws IOException, InterruptedException {
            Map<String, Object> body = new HashMap<>();
            body.put("amount_cents", amountCents);
            if (reference != null) body.put("reference", reference);
            return call("POST", "/v1/billing/admin/invoices/" + invoiceId + "/pay", body, null);
        }

        public Map<String, Object> voidInvoice(String invoiceId) throws IOException, InterruptedException {
            return call("POST", "/v1/billing/admin/invoices/" + invoiceId + "/void", null, null);
        }

        public Map<String, Object> revenueSummary() throws IOException, InterruptedException {
            return call("GET", "/v1/billing/admin/revenue-summary", null, null);
        }

        public List<Map<String, Object>> revenueMonthly() throws IOException, InterruptedException {
            return callList("GET", "/v1/billing/admin/revenue-monthly", null);
        }

        public void suspendOrg(String organizationId) throws IOException, InterruptedException {
            call("POST", "/v1/orgs/" + organizationId + "/suspend", null, null);
        }

        public void unsuspendOrg(String organizationId) throws IOException, InterruptedException {
            call("DELETE", "/v1/orgs/" + organizationId + "/suspend", null, null);
        }
    }

    // ── request core ──────────────────────────────────────────────────────────

    private Map<String, Object> call(String method, String path, Object body, Map<String, String> params)
            throws IOException, InterruptedException {
        return parseMap(send(method, path, body, params, null, null));
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> callList(String method, String path, Object body)
            throws IOException, InterruptedException {
        HttpResponse<byte[]> resp = send(method, path, body, null, null, null);
        raiseIfError(resp);
        return mapper.readValue(resp.body(), List.class);
    }

    @SuppressWarnings("unchecked")
    private Page callPage(String path, Integer limit, Integer offset, Map<String, String> extra)
            throws IOException, InterruptedException {
        HttpResponse<byte[]> resp = send("GET", path, null, paging(limit, offset, extra), null, null);
        raiseIfError(resp);
        List<Map<String, Object>> items = mapper.readValue(resp.body(), List.class);
        int total = resp.headers().firstValue("X-Total-Count").map(Integer::parseInt).orElse(items.size());
        return new Page(items, total, limit == null ? 50 : limit, offset == null ? 0 : offset);
    }

    private byte[] callBytes(String path) throws IOException, InterruptedException {
        HttpResponse<byte[]> resp = send("GET", path, null, null, null, null);
        raiseIfError(resp);
        return resp.body();
    }

    private HttpResponse<byte[]> send(String method, String path, Object body, Map<String, String> params,
                                      HttpRequest.BodyPublisher rawBody, String rawContentType)
            throws IOException, InterruptedException {
        StringBuilder uri = new StringBuilder(baseUrl).append(path);
        if (params != null && !params.isEmpty()) {
            StringJoiner query = new StringJoiner("&");
            params.forEach((k, v) -> query.add(
                URLEncoder.encode(k, StandardCharsets.UTF_8) + "=" + URLEncoder.encode(v, StandardCharsets.UTF_8)));
            uri.append('?').append(query);
        }
        HttpRequest.Builder req = HttpRequest.newBuilder(URI.create(uri.toString()))
            .header("Authorization", authHeader);
        if (orgId != null) req.header("X-Org-Id", orgId);

        if (rawBody != null) {
            req.method(method, rawBody).header("Content-Type", rawContentType);
        } else if (body != null) {
            req.method(method, HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
               .header("Content-Type", "application/json");
        } else {
            req.method(method, HttpRequest.BodyPublishers.noBody());
        }
        return http.send(req.build(), HttpResponse.BodyHandlers.ofByteArray());
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseMap(HttpResponse<byte[]> resp) throws IOException {
        if (resp.statusCode() == 204) return null;
        raiseIfError(resp);
        return mapper.readValue(resp.body(), Map.class);
    }

    @SuppressWarnings("unchecked")
    private void raiseIfError(HttpResponse<byte[]> resp) throws IOException {
        if (resp.statusCode() < 400) return;
        Map<String, Object> problem;
        try {
            problem = mapper.readValue(resp.body(), Map.class);
        } catch (IOException e) {
            problem = Map.of("title", "http_error", "detail", new String(resp.body(), StandardCharsets.UTF_8));
        }
        throw SynapseException.forStatus(resp.statusCode(), problem);
    }

    private static Map<String, String> paging(Integer limit, Integer offset, Map<String, String> extra) {
        Map<String, String> params = new HashMap<>();
        if (extra != null) extra.forEach((k, v) -> { if (v != null) params.put(k, v); });
        if (limit != null) params.put("limit", String.valueOf(limit));
        if (offset != null) params.put("offset", String.valueOf(offset));
        return params;
    }

    private static String trimSlash(String s) {
        String out = s;
        while (out.endsWith("/")) out = out.substring(0, out.length() - 1);
        return out;
    }
}
