package dev.synapse.client;

import java.util.Map;
import java.util.List;

/** Any non-2xx API response, carrying the problem+json body. */
public class SynapseException extends RuntimeException {

    private final int status;
    private final Map<String, Object> body;

    public SynapseException(int status, Map<String, Object> body) {
        super(message(body, status));
        this.status = status;
        this.body = body;
    }

    private static String message(Map<String, Object> body, int status) {
        Object detail = body.get("detail");
        Object title = body.get("title");
        if (detail != null) return String.valueOf(detail);
        if (title != null) return String.valueOf(title);
        return "API error " + status;
    }

    public int getStatus() { return status; }
    public Map<String, Object> getBody() { return body; }

    /** 401 — bad credentials (or revoked/expired key). */
    public static class AuthException extends SynapseException {
        public AuthException(int status, Map<String, Object> body) { super(status, body); }
    }

    /** 404 — missing resource, or cross-tenant (identical by design). */
    public static class NotFoundException extends SynapseException {
        public NotFoundException(int status, Map<String, Object> body) { super(status, body); }
    }

    /** 402 — plan limit exceeded. */
    public static class LimitException extends SynapseException {
        public LimitException(int status, Map<String, Object> body) { super(status, body); }

        @SuppressWarnings("unchecked")
        public String metric() {
            Object m = getBody().get("metric");
            return m != null ? String.valueOf(m) : null;
        }

        public Integer limit() {
            Object l = getBody().get("limit");
            return l instanceof Number n ? n.intValue() : null;
        }
    }

    /** 403 feature_not_entitled — carries upgrade hints. */
    public static class FeatureGatedException extends SynapseException {
        public FeatureGatedException(int status, Map<String, Object> body) { super(status, body); }

        public String feature() {
            Object f = getBody().get("feature");
            return f != null ? String.valueOf(f) : null;
        }

        @SuppressWarnings("unchecked")
        public List<String> availableIn() {
            Object a = getBody().get("available_in");
            return a instanceof List<?> list ? (List<String>) list : List.of();
        }
    }

    static SynapseException forStatus(int status, Map<String, Object> body) {
        if (status == 401) return new AuthException(status, body);
        if (status == 404) return new NotFoundException(status, body);
        if (status == 402) return new LimitException(status, body);
        if (status == 403 && body.containsKey("feature")) {
            return new FeatureGatedException(status, body);
        }
        return new SynapseException(status, body);
    }
}
