# Synapse SDKs

Typed clients for the Synapse SaaS Framework API — one per ecosystem:

| Language | Path | Runtime dep | Tests |
|---|---|---|---|
| Python | [`python/`](python/) | httpx | 9 |
| TypeScript | [`typescript/`](typescript/) | none (platform fetch) | 9 |
| Go | [`go/`](go/) | none (stdlib) | 6 |
| Java | [`java/`](java/) | Jackson | 6 |

All four share the same surface and semantics:

- **Two credential modes**: API key (`sk_…` — org pinned server-side, no org
  header needed) or a user access token (+ optional org id for multi-org users)
- **Resource namespaces**: `auth`, `orgs`, `members`, `subscription`,
  `usage`, `entitlements`, `api_keys`
- **Typed errors** mirroring problem+json: 401 → auth, 402 → limit (with
  `metric`/`limit`), 403-feature → gate (with `feature`/`available_in`),
  404 → not-found (cross-tenant is indistinguishable by design)
- **204 → no content** on deletes/revokes

## Python

```python
from synapse_saas_client import SynapseClient

client = SynapseClient("https://api.example.com", api_key="sk_…")
usage = client.usage.summary()
for m in usage["metrics"]:
    print(m["metric"], m["used"], "/", m["limit"])

try:
    client.usage.consume("ai_tokens", 5_000)
except Exception as e:
    getattr(e, "metric", None)  # LimitError carries metric + limit
```

Async: `SynapseClient(..., is_async=True)` — every call is a coroutine.

## TypeScript

```typescript
import { SynapseClient } from "@synapse-saas/client";

const client = new SynapseClient("https://api.example.com", { apiKey: "sk_…" });
const usage = await client.usage.summary();
```

## Go

```go
client, _ := synapse.New("https://api.example.com", synapse.Options{APIKey: "sk_…"})

var limitErr *synapse.LimitError
if _, err := client.Usage().Consume(ctx, "ai_tokens", 5000); errors.As(err, &limitErr) {
    log.Printf("quota %s=%d tripped", limitErr.Metric(), limitErr.Limit())
}
```

## Java

```java
SynapseClient client = SynapseClient.withApiKey("https://api.example.com", "sk_…");

try {
    client.usage.consume("ai_tokens", 5_000);
} catch (SynapseException.LimitException e) {
    System.out.println("quota tripped: " + e.metric());
}
```

## Testing each SDK

```bash
cd sdk/python     && uv run --with httpx --with pytest --no-project \
                      python -m pytest test_client.py -q --rootdir=. -c /dev/null
cd sdk/typescript && pnpm install && pnpm build && pnpm test
cd sdk/go         && go test ./...
cd sdk/java       && mvn test
```
