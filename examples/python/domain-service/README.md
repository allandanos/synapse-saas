# domain-service (Python, API-key mode)

A standalone product service in Python that extends the framework **without**
importing framework internals — same server-to-server pattern as the Go/Java
variants, driven by an org API key. (The in-process extension model — where
your domain code lives inside the framework — is `examples/python/hello-saas`.)

## Run

```bash
export SYNAPSE_KEY=sk_…                       # org API key (console → API keys)
export SERVICE_TOKEN=my-product-token          # what YOUR clients present
uv run --project ../../../sdk/python domain_service.py   # listens on :8092
```

## Exercise it

```bash
curl localhost:8092/v1/plan -H "Authorization: Bearer my-product-token"

curl -X POST localhost:8092/v1/reports \
  -H "Authorization: Bearer my-product-token" \
  -d '{"prompt":"Q1 revenue analysis"}'
```
