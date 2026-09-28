# Porting guide — Java (Spring Boot) and TypeScript (NestJS)

The reference implementation is Python. The ports
([`synapse-saas-java`](https://github.com/allandanos/synapse-saas-java),
[`synapse-saas-node`](https://github.com/allandanos/synapse-saas-node), checked
out as siblings of this repo) implement the **same contract** — see
[ADR 0012](../docs/adr/0012-polyglot-ports-contract-first.md) for the rules.
This page is the working map: what each Python module becomes, what changes
shape, and in which order to build.

## The contract a port must satisfy

| Artifact | What it pins | How a port is checked |
|---|---|---|
| `contracts/openapi-v1.json` | 85 client operations + probes, schemas, status codes | `scripts/export_openapi.py --check` here; the port's own OpenAPI must list the same operations |
| `contracts/problems.json` | every problem title with its `status` and the exception `classes` that render it | `tests/conformance` asserts shapes; the port raises the same `type` URIs |
| `contracts/events.json` | public webhook events vs internal outbox events | payload keys are documented in `docs/webhooks.md`; internal events never fan out |
| `contracts/schema-v1.sql` | the schema at migration head (`pg_dump --schema-only`) | becomes `V1__baseline.sql` / `001_baseline.sql` |
| `tests/conformance` | black-box journeys per route family | `SYNAPSE_CONFORMANCE_API_URL=http://localhost:8080 uv run pytest tests/conformance -m "" --no-cov` |
| `sdk/*` test suites | client behaviour (pages, bytes, errors) | point each SDK's example at the port |
| `apps/web/e2e` | the console against the API | `E2E_API_URL=http://localhost:8080 pnpm exec playwright test` |

Platform-operator journeys need an operator account in the port:
`SYNAPSE_CONFORMANCE_ADMIN_EMAIL` / `SYNAPSE_CONFORMANCE_ADMIN_PASSWORD`.

Regenerate the baseline after every migration. Keep pg_dump's
`SET check_function_bodies = false;` line: `synapse_org_for_invite_token` is a
SQL-language function declared before `memberships`, so a runner that validates
bodies would fail (both ports set it per file).

```bash
make test-pg   # scratch DB at migration head
docker exec synapse-saas-postgres-test-1 pg_dump -U synapse --schema-only --no-owner \
  --no-privileges --no-comments synapse_test > contracts/schema-v1.sql
```

## Module map

Sizes are lines of Python today; "DI" says what changes shape in the target.

| Python module (lines) | Java package (`dev.synapse.*`) | Nest module | DI / shape notes |
|---|---|---|---|
| `core/config` (settings, prod guardrails) | `core.config` — `@ConfigurationProperties` + `@Validated` | `ConfigModule` + zod schema | keep the same `SYNAPSE_*` env names; keep the production guardrails (rate-limit ceilings, cookie flags, RLS role assertion) |
| `core/errors`, `api/app` (problem documents) | `ProblemDetail` + `@RestControllerAdvice` | `HttpExceptionFilter` | `type` URIs from `problems.json`; extras never shadow the RFC 7807 members; request-validation → `validation_failed` with `errors[]` |
| `core/context` (contextvars: request id, user, tenant, span) | `ScopedValue`/`ThreadLocal` holder set by a `OncePerRequestFilter`; MDC for logs | `nestjs-cls` (`AsyncLocalStorage`) populated by a global interceptor | the **only** place the tenant lives; repositories read it, never a parameter |
| `core/db` (session, RLS GUCs `app.current_user/current_tenant/rls_platform`) | `JdbcClient` + `TransactionSynchronization` callback that runs `SELECT set_config(...)` on the tx connection | TypeORM `QueryRunner` per request; `set_config` at tx start | GUCs are *transaction-local* (`set_config(..., true)`); worker/CLI use the owner DSN, API uses the RLS role |
| `core/cache` (`VersionedCache`, deferred bumps) | Spring Cache + Lettuce; bump on `afterCommit` | `cache-manager` + ioredis; bump in `afterCommit` hook | version-at-read semantics; Redis required (no TTL-dict fallback) |
| `core/outbox`, `core/events` | `OutboxWriter` in the same `@Transactional` | `OutboxService` in the same tx | `audience` column; internal events listed in `events.json` |
| `core/rate_limit`, `identity/rate_limit` | Bucket4j on Redis; fail **open** on infra errors | `rate-limiter-flexible`; fail open | trusted-proxy XFF rule is contract |
| `core/commit_before_send` | **not ported** — services are `@Transactional`; controllers serialise after commit | **not ported** — same | the guarantee (write visible to the next request) is tested by conformance |
| `identity/*` (argon2, JWT HS256, refresh rotation, OIDC+PKCE, JWKS cache) | Spring Security resource server + `ApiKeyAuthenticationFilter`; `spring-security-oauth2-client` for the code flow | Passport-JWT + `ApiKeyGuard`; `openid-client` | same token claims (`sub`, `org`, `exp`); SSO-only users answer 401 `sso_url` |
| `tenancy/*` (orgs, memberships, invites, suspension) | `tenancy` package; Hibernate `@TenantId` on tenant entities + `@Filter` | `TenancyModule`; TypeORM subscriber adds `organization_id` predicates | 404 for non-members, 403 `organization_suspended` after membership check |
| `authorization/*` (RBAC catalog, custom roles, OpenFGA model + client + sync) | `AuthorizationService` + `@PreAuthorize("@authz.can('billing:manage')")`; FGA via WebClient | `PermissionsGuard` + `@RequirePermission()`; FGA via fetch | the catalog is data (`permissions.py` → JSON); FGA model generator is pure logic — transliterate with tests |
| `subscriptions/*` (catalog, state machine, proration, sync) | pure classes + `SubscriptionService` | pure classes + `SubscriptionsService` | **transliterate** `state_machine.py`, `proration.py`, `catalog.py` validation with their unit tests |
| `entitlements/*` (resolver, cache, grants) | `EntitlementResolver` (pure) + cached service | same | **transliterate** `resolver.py`; the cache serializer must carry `overage` |
| `usage/*` (counters, gauges, idempotency ledger, batch) | `UsageService` with `JdbcClient` for the `INSERT … ON CONFLICT` and advisory-lock paths | `UsageService` with raw SQL | 16 raw-SQL sites in Python become native queries; keep `usage_idempotency_keys` semantics |
| `billing/*` (providers, checkout, webhooks ledger, invoicing, PDF, reporting) | `billing.providers.*` behind a `BillingProvider` interface with `Capability` set; `openpdf` for PDFs | `BillingProvider` interface; `pdfkit` | Stripe/Paddle/Xendit/PayMongo signature rules in `docs/billing-providers.md`; money in integer minor units |
| `webhooks/*` (endpoints, deliveries, HMAC signing, retry ladder) | `WebhookDispatcher` with `SELECT … FOR UPDATE SKIP LOCKED` | same | signature spec in `docs/webhooks.md`; backoff ladder + `exhausted` is contract |
| `storage/*` (local + S3, presign, gauge quota) | `StorageBackend` interface; AWS SDK v2 presigner | `@aws-sdk/s3-request-presigner` | `presign_unsupported` 409 on local disk; `storage_bytes` is a gauge |
| `feature_flags/*`, `api_keys/*`, `audit/*`, `agents/*` | straightforward CRUD packages | straightforward modules | API keys: create-time scope subset + auth-time intersection with the creator's *current* permissions |
| `notifications/*` | `JavaMailSender` behind `Notifier` | `nodemailer` behind `Notifier` | Noop notifier when unconfigured |
| `worker/jobs` (outbox dispatch, deliveries, rollups, expiry, recurring billing, partitions, purge) | `@Scheduled` + ShedLock, one bean per job, `synapse-cli jobs run-once` equivalent as a Spring Boot `ApplicationRunner` profile | `@nestjs/schedule` + BullMQ; `run-once` as a CLI command | per-item savepoints; `SKIP LOCKED`; emails after commit |
| `migrations/*` | Flyway: `V1__baseline.sql` + mirrored SQL | raw SQL runner (e.g. `node-pg-migrate` in SQL mode) | never translate Alembic files; mirror DDL |
| `cli`, `scaffold/*` | Spring Boot `ApplicationRunner` commands; Maven archetype | Nest CLI commands; Nest schematic | scaffold templates are per-port |
| `testing/fixtures` | Testcontainers Postgres + `@SpringBootTest` fixtures published as a `-test-fixtures` jar | Testcontainers + supertest helpers in `@synapse-saas/testing` | products test against the same fixture names |

Raw SQL today: 93 `text(...)` sites (excluding migrations), all Postgres-portable.
Partitioned `usage_events`, BRIN indexes, partial unique indexes and RLS policies
must remain raw DDL in every port.

## Build order and milestones

| # | Scope | Gate | Java | TS |
|---|---|---|---|---|
| 1 | pure logic + core (config, problems, context, DB/RLS, cache, outbox writer) + `/healthz` `/readyz` `/v1/meta` | unit tests ported 1:1; `test_meta_and_health` conformance | wk 4 | wk 4 |
| 2 | identity, tenancy, authorization (RBAC) | `test_auth`, `test_tenancy`, `test_authorization`, `test_api_keys` | wk 9 | wk 10 |
| 3 | subscriptions, entitlements, usage | `test_subscriptions`, `test_usage_and_entitlements` | wk 12 | wk 13 |
| 4 | billing providers (manual + Stripe first), invoicing, reporting, worker jobs | `test_billing`; recurring-billing + outbox worker tests | wk 14 | wk 16 |
| 5 | webhooks, files, flags, audit, agents | remaining conformance modules; all four SDK suites | wk 16 | wk 18 |
| 6 | console parity | `E2E_API_URL` Playwright 22/22 | wk 18 | wk 20 |
| 7 | OIDC + OpenFGA adapters, hardening, release | nightly `e2e-sso`, FGA parity matrix | wk 20–24 | wk 22–27 |

Estimates assume one senior engineer per port, working from this repository's
tests rather than from its source.

## Naming and coordinates

Decided by the owner (2026-09-28). All three live under `allandanos` for now;
the planned move to a `98labs` organization is the owner's call.

| | Reference | Java | Node |
|---|---|---|---|
| Repository | `allandanos/synapse-saas` | `allandanos/synapse-saas-java` | `allandanos/synapse-saas-node` |
| Package | PyPI `synapse-saas` | Maven `dev.synapse:synapse-saas` | npm `@synapse-saas/server` |
| Client SDK | `synapse-saas-client` | `dev.synapse:synapse-saas-client` (this repo) | `@synapse-saas/client` (this repo) |

Moving the repositories to another organization changes the Go SDK module path
(`github.com/allandanos/synapse-saas/sdk/go`) — do it once, before external
dependents exist, and bump the Go module major if a tag has already shipped.
