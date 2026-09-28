# ADR 0012 — Polyglot ports are contract-first sibling repositories

- **Status:** accepted (2026-09-28)
- **Deciders:** framework maintainers
- **Supersedes / amends:** extends ADR 0001 (monorepo layout) and ADR 0011 (distribution)

## Context

The framework's owner wants the same platform available to JVM and Node teams
as *native* stacks — Spring Boot and NestJS — not only through the REST API
(`docs/extending.md`, model 2). The Python implementation is the reference:
it carries the business rules, the schema, and the tests.

A port that re-reads the Python source module by module will reproduce its
accidental choices and drift as soon as the reference moves. What must stay
identical between implementations is the **contract**: the HTTP surface, the
problem documents, the event vocabulary, the schema, and the observable
behaviour a client can distinguish. Everything else (DI style, ORM, job
runner) should be idiomatic to the target.

By the time of this decision the contract is frozen and machine-checked:
`contracts/openapi-v1.json` (85 client operations + probes), `events.json`,
`problems.json`, `schema-v1.sql`, the black-box `tests/conformance` suite, four
SDK suites, and the console's Playwright journeys.

## Decision

1. **One contract, N implementations.** `contracts/` in this repository is the
   single source of truth. A port never changes it; a behaviour a port needs is
   first added here (with its conformance test), then implemented there.
2. **Sibling repositories, not subdirectories:** `synapse-saas-java`
   (Spring Boot 3.4 / Java 21) and `synapse-saas-ts` (NestJS 11 / TypeScript),
   each with its own release cadence and package coordinates
   (`dev.synapse:synapse-saas`, `@synapse-saas/server`). The reference stays
   `synapse-saas` on PyPI. (`synapse-saas-node` is the alternative name for the
   Node port if the maintainers prefer runtime over language in the name.)
3. **Acceptance is the conformance suite, not code review of a translation.**
   A route family is *done* in a port when
   `SYNAPSE_CONFORMANCE_API_URL=<port> pytest tests/conformance` passes for it,
   the four SDK suites pass against it, and — once the surface is complete —
   the unmodified console's Playwright journeys pass with `E2E_API_URL`
   pointing at it.
4. **Schema originates in Python.** New tables and columns land as Alembic
   migrations here. Each port starts from `contracts/schema-v1.sql`
   (`pg_dump --schema-only` at migration head) as its Flyway `V1__baseline.sql`
   / raw `001_baseline.sql`, and mirrors later migrations as plain SQL.
   Postgres-specific DDL (range partitioning, BRIN, partial unique indexes,
   CITEXT, RLS policies) stays raw SQL in every implementation; no port uses an
   ORM feature that cannot express it (which rules out Prisma for the TS port).
5. **What is deliberately not ported:** FastAPI's yield-dependencies
   (replaced by filters/guards + `@Transactional` / interceptors),
   `CommitBeforeSendMiddleware` (transactions commit in the service layer
   before the controller serialises), the TTL-dict cache fallback (Redis is
   required), Alembic (see 4), and the `synapse-cli new` scaffold templates
   (each port ships its own archetype/schematic).
6. **Pure logic is transliterated with its unit tests:** the entitlement
   resolver, the subscription state machine, proration, the permission
   catalog, the OpenFGA model generator, webhook signing, and the event
   vocabulary. These are the only places where a line-by-line port is the
   right move, and their Python tests are the spec.
7. **Module order** (each milestone gated by conformance):
   pure logic → core (config, problem documents, request context, DB + RLS
   GUCs, cache, outbox writer) → identity / tenancy / authorization →
   subscriptions / entitlements / usage → billing providers + invoicing →
   worker jobs → webhooks / files / flags / keys / audit / agents →
   OIDC + OpenFGA adapters.

`ports/README.md` holds the module-by-module map (Python module → Java package
→ Nest module, with the DI redesign notes) and the milestone plan.

## Consequences

- Behavioural parity is measurable: the same `tests/conformance` run, the same
  pass set. Divergence is a failing test, not a code-review opinion.
- The reference implementation gains discipline: contract changes need a
  CHANGELOG entry, an OpenAPI diff, a conformance test, and SDK coverage
  (`scripts/sdk_coverage.py --check`) *before* they can reach a port.
- Three codebases to maintain. The mitigation is that only the contract is
  shared; a bug in the Java DI layer is a Java bug, never a cross-repo one.
- Ports lag the reference. Each port's README states the contract version it
  passes (`contracts/CHANGELOG.md` heading) so consumers can tell.
- Estimated effort per port, one senior engineer: 16–27 engineer-weeks
  (module order above; Java slightly favoured because Hibernate `@TenantId`,
  `@Transactional`, `ProblemDetail`, Micrometer and ShedLock are first-party).
