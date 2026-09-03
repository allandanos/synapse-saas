# Observability

Two pillars: **Prometheus metrics** (always on, `/metrics`) and **OpenTelemetry
tracing** (compiled in, inert until you point it at a collector).

## Prometheus

```bash
SYNAPSE_METRICS_ENABLED=true   # default; false ⇒ /metrics 404s
```

Scrape `/metrics`. Series (all with bounded cardinality — route *templates*
and fixed enums only, never org ids/emails/keys):

| Series | Labels | What it answers |
|---|---|---|
| `synapse_http_requests_total` | method, route, status_class | traffic shape, error rates per endpoint |
| `synapse_http_request_duration_seconds` | method, route | latency histograms |
| `synapse_auth_events_total` | event | logins, failures, registrations, rate-limited |
| `synapse_api_key_auth_total` | outcome | programmatic traffic, invalid key probes |
| `synapse_business_events_total` | event | org created, invites, plan changes… |
| `synapse_usage_limited_total` | metric | 402s by which quota |
| `synapse_feature_gated_total` | feature | 403 gates by which feature |
| `synapse_webhook_deliveries_total` | outcome | delivered/failed/exhausted |
| `synapse_emails_total` | outcome | sent/suppressed/failed |
| `synapse_worker_jobs_total` / `_duration_seconds` | job[, outcome] | worker health |
| `synapse_db_pool_connections` | state | pool pressure |

Suggested alerts: 5xx rate on `http_requests_total{status_class="5xx"}`,
`usage_limited_total` spike (upgrade friction), `webhook_deliveries
{outcome="exhausted"}` > 0, `db_pool_connections{state="checked_out"}` near
pool size.

## OpenTelemetry tracing

```bash
# Inert by default. Point at any OTLP gRPC collector to enable:
SYNAPSE_OTEL_EXPORTER_ENDPOINT=http://tempo:4317
SYNAPSE_OTEL_SERVICE_NAME=synapse-saas
```

- One **server span per request** (`METHOD /path`), started by the request
  middleware regardless of exporter state — code paths are identical with
  tracing on or off
- **Trace correlation everywhere**: the active trace id flows into structlog
  (`trace_id=` on every log line inside a span) and into problem documents
  (`request_id` falls back to the trace id) — a 4xx/5xx body names the exact
  trace your APM shows
- Resource attributes: `service.name`, `service.version`,
  `deployment.environment`

### Adding spans in domain code

```python
from synapse_saas.core.tracing import get_tracer

with get_tracer("synapse.billing").start_as_current_span("checkout"):
    ...  # child of the request span; shares its trace id
```

### Local exploration

`docker compose --profile extras up` includes a collector-less path — point
the endpoint at any local Tempo/Jaeger (`localhost:4317` via their gRPC
ports) and spans appear with full request→service correlation.

## Design rules

- Instrumentation is **best-effort by construction**: every metric/span site
  wraps in `contextlib.suppress` — metrics/tracing can never fail the request
  or job they measure
- **Bounded cardinality** is enforced at the label level: unmatched routes
  collapse to `unmatched`, statuses to `2xx`-`5xx`, events to fixed vocabularies
