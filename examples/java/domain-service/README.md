# domain-service (Java)

A real product service extending the framework from Java: it owns its domain
(`POST /v1/reports`) and delegates tenancy decisions to the Synapse API
server-to-server. Same pattern as the Go variant.

## The pattern

```
client ──your auth──▶ Java service ──org API key──▶ Synapse API
                       │  1. entitlements.effective → feature gate (403)
                       │  2. usage.consume(ai_tokens) → quota gate (402)
                       └─ 3. domain work
```

## Run

```bash
# SDK installed locally first: cd sdk/java && mvn install
export SYNAPSE_KEY=sk_…                       # org API key (console → API keys)
export SERVICE_TOKEN=my-product-token          # what YOUR clients present
mvn -q compile exec:java \
  -Dexec.mainClass=dev.synapse.example.DomainServiceSample   # listens on :8091
```

## Exercise it

```bash
curl localhost:8091/v1/plan -H "Authorization: Bearer my-product-token"

curl -X POST localhost:8091/v1/reports \
  -H "Authorization: Bearer my-product-token" \
  -d '{"prompt":"Q1 revenue analysis"}'
```
