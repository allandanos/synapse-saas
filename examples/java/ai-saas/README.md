# ai-saas — metering an AI product (Go + Java samples)

The SynapseDev.AI shape: every inference call meters `ai_tokens`/`ai_requests`
against the org's plan, and quota breaches arrive as typed errors you can bill
around. The `ai_tokens` and `ai_requests` metrics ship in the default catalog.

## Go sample

```bash
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_KEY=sk_…   # an API key for the org

cd examples/ai-saas/go
go run ./main.go
```

## Java sample

```bash
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_KEY=sk_…

cd examples/ai-saas/java
mvn -q compile exec:java -Dexec.mainClass=dev.synapse.example.AiSaasSample
```

(Or copy `AiSaasSample.java` into any project with the SDK dependency.)

## What they show

- A metered inference call: tokens consumed atomically, limit checked
  server-side *before* the work counts
- `synapse.LimitError` / `SynapseException.LimitException` carrying
  `metric` + `limit` — route to an upgrade prompt or a pay-as-you-go
  overage instead of a hard failure
- API-key auth: no org header, no user session — the key IS the org
