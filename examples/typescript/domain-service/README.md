# domain-service (TypeScript)

A real product service extending the framework from Node/TypeScript: it owns
its domain (`POST /v1/reports`) and delegates tenancy decisions to the Synapse
API server-to-server. Same pattern as the Go/Java variants.

## Run

```bash
export SYNAPSE_KEY=sk_…                       # org API key (console → API keys)
export SERVICE_TOKEN=my-product-token          # what YOUR clients present
pnpm install && pnpm start                     # listens on :8093
```

## Exercise it

```bash
curl localhost:8093/v1/plan -H "Authorization: Bearer my-product-token"

curl -X POST localhost:8093/v1/reports \
  -H "Authorization: Bearer my-product-token" \
  -d '{"prompt":"Q1 revenue analysis"}'
```
