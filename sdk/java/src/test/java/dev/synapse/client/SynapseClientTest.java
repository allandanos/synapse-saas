package dev.synapse.client;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.junit.jupiter.api.Assertions.*;

class SynapseClientTest {

    private HttpServer server;
    private SynapseClient client;
    private final List<String> paths = new CopyOnWriteArrayList<>();
    private volatile String lastAuthHeader;
    private volatile String lastOrgHeader;
    private volatile String lastBody;
    private volatile String lastQuery;
    private volatile String lastContentType;
    private volatile int respondStatus = 200;
    private volatile String respondBody = "{}";
    private volatile String respondContentType = "application/json";
    private volatile String respondTotalCount;

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/", exchange -> {
            paths.add(exchange.getRequestMethod() + " " + exchange.getRequestURI().getPath());
            lastAuthHeader = exchange.getRequestHeaders().getFirst("Authorization");
            lastOrgHeader = exchange.getRequestHeaders().getFirst("X-Org-Id");
            lastBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            lastQuery = exchange.getRequestURI().getQuery();
            lastContentType = exchange.getRequestHeaders().getFirst("Content-Type");
            byte[] body = respondBody.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", respondContentType);
            if (respondTotalCount != null) exchange.getResponseHeaders().set("X-Total-Count", respondTotalCount);
            exchange.sendResponseHeaders(respondStatus, respondStatus == 204 ? -1 : body.length);
            if (respondStatus != 204) {
                try (OutputStream out = exchange.getResponseBody()) {
                    out.write(body);
                }
            } else {
                exchange.close();
            }
        });
        server.start();
        int port = server.getAddress().getPort();
        client = SynapseClient.builder("http://localhost:" + port, "sk_test", null)
            .orgId("11111111-1111-1111-1111-111111111111")
            .build();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    @Test
    void authAndOrgHeadersSent() throws Exception {
        respondBody = "{\"id\":\"u1\"}";
        Map<String, Object> me = client.auth.me();
        assertEquals("u1", me.get("id"));
        assertEquals("Bearer sk_test", lastAuthHeader);
        assertEquals("11111111-1111-1111-1111-111111111111", lastOrgHeader);
    }

    @Test
    void consumePayloadShaped() throws Exception {
        respondBody = "{\"total\":5}";
        Map<String, Object> out = client.usage.consume("api_requests", 5);
        assertEquals(5, ((Number) out.get("total")).intValue());
        assertTrue(lastBody.contains("\"metric\":\"api_requests\""));
        assertTrue(lastBody.contains("\"quantity\":5"));
    }

    @Test
    void noContentReturnsNull() throws Exception {
        respondStatus = 204;
        assertDoesNotThrow(() -> client.apiKeys.revoke("k1"));
        assertTrue(paths.get(0).startsWith("DELETE /v1/api-keys/k1"));
    }

    @Test
    void limitExceptionTypedWithMetric() {
        respondStatus = 402;
        respondBody = "{\"title\":\"usage limit exceeded\",\"metric\":\"api_requests\",\"limit\":100}";
        SynapseException.LimitException ex = assertThrows(
            SynapseException.LimitException.class,
            () -> client.usage.consume("api_requests", 500));
        assertEquals("api_requests", ex.metric());
        assertEquals(100, ex.limit());
    }

    @Test
    void featureGateExceptionTyped() {
        respondStatus = 403;
        respondBody = "{\"title\":\"feature not entitled\",\"feature\":\"advanced_reports\",\"available_in\":[\"pro\"]}";
        SynapseException.FeatureGatedException ex = assertThrows(
            SynapseException.FeatureGatedException.class,
            () -> client.subscription.change("pro"));
        assertEquals("advanced_reports", ex.feature());
        assertEquals(List.of("pro"), ex.availableIn());
    }

    @Test
    void pagesReadTotalHeaderAndPassParams() throws Exception {
        respondBody = "[{\"id\":\"a\"},{\"id\":\"b\"}]";
        respondTotalCount = "7";
        SynapseClient.Page page = client.invoices.list(2, 4);
        assertEquals(7, page.total());
        assertEquals(2, page.items().size());
        assertEquals(2, page.limit());
        assertEquals(4, page.offset());
        assertTrue(lastQuery.contains("limit=2") && lastQuery.contains("offset=4"), lastQuery);
        assertTrue(paths.get(0).startsWith("GET /v1/billing/invoices"));
    }

    @Test
    void queryParamsAreHonoured() throws Exception {
        respondBody = "[]";
        client.webhooks.listDeliveries(10, null, "e1");
        assertTrue(lastQuery.contains("endpoint_id=e1") && lastQuery.contains("limit=10"), lastQuery);
        respondBody = "{}";
        client.usage.check("api_requests", 3);
        assertTrue(lastQuery.contains("metric=api_requests") && lastQuery.contains("quantity=3"), lastQuery);
    }

    @Test
    void bytesRoutesReturnRawBody() throws Exception {
        respondContentType = "application/pdf";
        respondBody = "%PDF-1.7";
        byte[] pdf = client.invoices.pdf("inv1");
        assertEquals("%PDF-1.7", new String(pdf, StandardCharsets.UTF_8));
        assertTrue(paths.get(0).startsWith("GET /v1/billing/invoices/inv1/pdf"));
    }

    @Test
    void bytesRouteErrorsStillMap() {
        respondStatus = 404;
        respondBody = "{\"title\":\"not found\"}";
        assertThrows(SynapseException.NotFoundException.class, () -> client.files.download("nope"));
    }

    @Test
    void uploadIsMultipart() throws Exception {
        respondStatus = 201;
        respondBody = "{\"id\":\"f1\"}";
        Map<String, Object> out = client.files.upload("a.txt", "hello".getBytes(StandardCharsets.UTF_8), "text/plain");
        assertEquals("f1", out.get("id"));
        assertTrue(lastContentType.startsWith("multipart/form-data; boundary="), lastContentType);
        assertTrue(lastBody.contains("filename=\"a.txt\"") && lastBody.contains("hello"), lastBody);
    }

    @Test
    void payloadShapes() throws Exception {
        client.auth.login("a@b.c", "pw");
        assertTrue(lastBody.contains("\"email\":\"a@b.c\"") && lastBody.contains("\"password\":\"pw\""), lastBody);
        client.featureFlags.setOverride("k", Map.of("enabled", true, "organization_id", "o1"));
        assertTrue(lastBody.contains("\"organization_id\":\"o1\""), lastBody);
        respondBody = "[]";
        client.usage.record(List.of(Map.of("metric", "api_requests", "quantity", 2, "idempotency_key", "k1")));
        assertTrue(paths.get(paths.size() - 1).startsWith("POST /v1/usage/events"));
        assertTrue(lastBody.contains("\"idempotency_key\":\"k1\""), lastBody);
        respondStatus = 204;
        client.admin.suspendOrg("org1");
        assertTrue(paths.get(paths.size() - 1).startsWith("POST /v1/orgs/org1/suspend"));
        client.admin.revokeGrant("org1", "g1");
        assertTrue(paths.get(paths.size() - 1).startsWith("DELETE /v1/admin/orgs/org1/entitlements/grants/g1"));
    }

    @Test
    void requiresCredentials() {
        assertThrows(IllegalArgumentException.class,
            () -> SynapseClient.builder("http://test", null, null));
    }
}
