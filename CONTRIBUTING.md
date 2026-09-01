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
