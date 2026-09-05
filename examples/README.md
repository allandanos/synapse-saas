# Examples

Every example type in every SDK language — 4 × 5. All run against a live
compose stack; each demonstrates the same framework behaviors with the
idioms of its language.

| | Python | TypeScript | Go | Java |
|---|---|---|---|---|
| **hello-saas** | [`python/`](python/hello-saas/)¹ | [`typescript/`](typescript/hello-saas/) | [`go/`](go/hello-saas/) | [`java/`](java/hello-saas/) |
| **multi-tenant** | [`python/`](python/multi-tenant/) | [`typescript/`](typescript/multi-tenant/) | [`go/`](go/multi-tenant/) | [`java/`](java/multi-tenant/) |
| **subscription** | [`python/`](python/subscription/) | [`typescript/`](typescript/subscription/) | [`go/`](go/subscription/) | [`java/`](java/subscription/) |
| **ai-saas** | [`python/`](python/ai-saas/) | [`typescript/`](typescript/ai-saas/) | [`go/`](go/ai-saas/) | [`java/`](java/ai-saas/) |
| **domain-service** | [`python/`](python/domain-service/)² | [`typescript/`](typescript/domain-service/)² | [`go/`](go/domain-service/)² | [`java/`](java/domain-service/)² |

¹ The Python hello-saas is the **server-side extension** variant — it defines
a real `Project(TenantMixin)` ORM model + router inside the framework process.
Every other hello-saas cell is a **client-side** script driving the running
API through its SDK.

² domain-service cells are the **polyglot extension** variant: a real HTTP
service per language owning its own domain endpoints, delegating entitlement
gates and usage metering to the framework server-to-server with an org API
key. See [docs/extending.md](../docs/extending.md) for the two extension
models and when to pick which.

## The example types

| Type | Shows |
|---|---|
| **hello-saas** | a complete domain app: tenant scoping, plan caps as typed 402s, per-project gauge metering |
| **multi-tenant** | one user, two orgs: per-org usage/members/entitlements, cross-tenant 404s |
| **subscription** | freemium lifecycle: quota wall (upgrade hints) → trial grant without a plan change → plan upgrade |
| **ai-saas** | the SynapseDev.AI shape: metered inference calls (`ai_tokens`), typed quota errors to bill around, automatic `api_requests` metering on key auth |
| **domain-service** | a real product service per language: own domain endpoints, own auth, SDK-driven feature gates (403) + quota walls (402) + metering |

## Common setup

```bash
docker compose up -d          # the stack (console at localhost:3000)
# register a user + org in the console, then:
export SYNAPSE_API=http://localhost:8000
export SYNAPSE_TOKEN=<access token>   # hello-saas, multi-tenant, subscription
export SYNAPSE_ORG=<org uuid>        # org-scoped examples
export SYNAPSE_KEY=sk_…              # ai-saas (console → API keys)
```

## Running

```bash
# Python (any example dir)
uv run --project ../../../sdk/python <script>.py

# TypeScript (any example dir)
pnpm install && pnpm start

# Go (any example dir)
go run .

# Java (any example dir; SDK installed locally first: cd sdk/java && mvn install)
mvn -q compile exec:java -Dexec.mainClass=dev.synapse.example.<Sample>
```

## Verification status

All 16 cells build/typecheck: Python (`ast`), TypeScript (`tsc --strict`,
clean installs), Go (`go vet` + `go build`), Java (`mvn compile`). Each
SDK's unit tests (30 total) live in `sdk/`.
