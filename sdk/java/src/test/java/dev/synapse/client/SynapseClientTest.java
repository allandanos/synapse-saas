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
    private volatile int respondStatus = 200;
    private volatile String respondBody = "{}";

    @BeforeEach
    void start() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/", exchange -> {
            paths.add(exchange.getRequestMethod() + " " + exchange.getRequestURI().getPath());
            lastAuthHeader = exchange.getRequestHeaders().getFirst("Authorization");
            lastOrgHeader = exchange.getRequestHeaders().getFirst("X-Org-Id");
            lastBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            byte[] body = respondBody.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
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
    void requiresCredentials() {
        assertThrows(IllegalArgumentException.class,
            () -> SynapseClient.builder("http://test", null, null));
    }
}
