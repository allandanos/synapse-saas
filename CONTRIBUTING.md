# Contributing to Synapse SaaS Framework

Thanks for your interest in contributing.

## Getting started

```bash
git clone https://github.com/allandanos/synapse-saas.git
cd synapse-saas
cp .env.example .env
make install
docker compose up -d postgres redis
make migrate && make seed
make test        # unit
make test-pg     # integration
```

## Development workflow

1. Branch from `main`: `feat/<short-description>` or `fix/<short-description>`
2. Make your change. Keep the layering contract:
   - `router.py` — HTTP concerns only, no business logic
   - `service.py` — domain logic; mutations write audit + outbox in the same transaction
   - `repository.py` — SQLAlchemy queries only
   - Modules may import `core` and their own package; never `api`/`worker` (enforced by import-linter)
3. Tests first for bug fixes (regression test), tests with the feature otherwise. Coverage gate is 80%.
4. `make lint typecheck test-all` must pass locally.
5. Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`

## Pull requests

- Describe the what and the why; link related issues
- Include test evidence (which suites ran)
- Security-sensitive changes (auth, billing, tenancy) will get extra review — expect it

## Reporting security issues

Do **not** open a public issue. Email allan.danos@gmail.com — see [SECURITY.md](SECURITY.md).

## License

By contributing you agree your contributions are licensed under Apache-2.0.

## Where things live (after ADR 0011)

- Migrations: `src/synapse_saas/migrations/versions/` (new revision:
  `uv run alembic -c database/alembic.ini revision -m "…"`; the root ini is a
  shim onto the packaged scripts). Numbering is sequential: `0018_…` next.
- Plan catalog: edit `config/plans.yaml` and copy it to
  `src/synapse_saas/config/plans.yaml` — a unit test fails when they differ.
- Test fixtures: `src/synapse_saas/testing/fixtures.py` (public plugin);
  `tests/integration/conftest.py` only re-exports helpers.

## Contract conformance

`tests/conformance` is a black-box suite over the frozen v1 contract. It runs
in-process by default (part of `make test-all`) and against any base URL:

```bash
SYNAPSE_CONFORMANCE_API_URL=http://localhost:8000 uv run pytest tests/conformance -m "" --no-cov
```

A route change is complete when the contract (`scripts/export_openapi.py --check`,
`scripts/export_contracts.py --check`), the docs (`scripts/check_docs.py --check`),
the four SDKs (`scripts/sdk_coverage.py --check`) and this suite all agree.
