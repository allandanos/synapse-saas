# domain-service (Go)

A real product service extending the framework from Go: it owns its domain
(`POST /v1/reports` — stand-in for your product's endpoints) and delegates
tenancy decisions to the Synapse API server-to-server.

## The pattern

```
client ──your auth──▶ Go service ──org API key──▶ Synapse API
                       │  1. Entitlements().Effective → feature gate (403)
                       │  2. Usage().Consume(ai_tokens) → quota gate (402)
                       └─ 3. domain work
```

## Run

```bash
# framework stack up; create an org API key (console → API keys)
export SYNAPSE_KEY=sk_…
export SERVICE_TOKEN=my-product-token   # what YOUR clients present
go run .                                # listens on :8090
```

## Exercise it

```bash
curl localhost:8090/v1/plan -H "Authorization: Bearer my-product-token"

curl -X POST localhost:8090/v1/reports \
  -H "Authorization: Bearer my-product-token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Q1 revenue analysis"}'
```

Grant `advanced_reports` (promo) or upgrade the org in the console to move
past the 403; watch the 402 arrive when the `ai_tokens` quota trips.
