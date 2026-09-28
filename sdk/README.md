# Synapse SDKs

Typed clients for the Synapse SaaS Framework API — one per ecosystem:

| Language | Path | Runtime dep | Tests |
|---|---|---|---|
| Python | [`python/`](python/) | httpx | 16 |
| TypeScript | [`typescript/`](typescript/) | none (platform fetch) | 14 |
| Go | [`go/`](go/) | none (stdlib) | 10 |
| Java | [`java/`](java/) | Jackson | 12 |

All four cover **every operation of the frozen contract** (`contracts/openapi-v1.json`,
gated in CI by `scripts/sdk_coverage.py --check`) with the same surface and semantics:

- **Two credential modes**: API key (`sk_…` — org pinned server-side, no org
  header needed) or a user access token (+ optional org id for multi-org users)
- **Resource namespaces** (one per route family):
  `auth` (register/login/refresh/logout/forgot/reset/accept-invite/me/switch-org),
  `orgs`, `members`, `roles` (+ permission catalog), `subscription` (+ plans),
  `usage` (record / consume / consume-batch / gauge / check / summary),
  `entitlements`, `billing` (checkout, portal, spend), `invoices` (draft →
  finalize → PDF bytes), `webhooks`, `files` (multipart upload, download bytes,
  presigned upload + complete), `feature_flags`, `agents`, `audit`, `api_keys`,
  `admin` (grants, invoice pay/void, revenue, suspend) and `meta()`
- **Pagination**: every list route takes `limit`/`offset`; the `*_page` /
  `listPage` / `List(…, Paging)` variants return `{items, total, limit, offset}`
  from `X-Total-Count`, the plain variants return the array
- **Bytes**: invoice PDFs and file downloads come back as raw bytes
  (`bytes` / `ArrayBuffer` / `[]byte` / `byte[]`); uploads are multipart
- **Typed errors** mirroring the problem documents: 401 → auth, 402 → limit
  (with `metric`/`limit`), 403-feature → gate (with `feature`/`available_in`),
  404 → not-found (cross-tenant is indistinguishable by design); every other
  status → the base error carrying the whole document
- **204 → no content** on deletes/revokes; platform-operator calls need a
  platform-admin bearer (ADR 0008)

Journeys that exercise the same surface end to end live in
[`tests/conformance`](../tests/conformance) — run them against any base URL
with `SYNAPSE_CONFORMANCE_API_URL`.

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
cd sdk/python     && uv run --with pytest --with pytest-asyncio --with respx \
                      pytest test_client.py -q -o addopts="" -o asyncio_mode=auto --rootdir .
cd sdk/typescript && pnpm install && pnpm build && pnpm test
cd sdk/go         && go test ./...
cd sdk/java       && mvn test
```
