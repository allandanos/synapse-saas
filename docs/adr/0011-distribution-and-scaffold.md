# ADR 0011: Distribution — a package, not a fork

## Status

Accepted (2026-09-28)

## Context

The framework was only consumable by cloning the repository: the plan
catalog and the Alembic scripts were resolved through a `REPO_ROOT` computed
from the source file's location, so a pip-installed `synapse_saas` could
neither load its default catalog nor migrate a database. The integration
fixtures lived in the repo's `tests/` tree, so a product built on the
framework had to copy them. Every real product would therefore have been a
fork, and forks do not receive fixes.

## Decision

- **Resources ship in the wheel.** `src/synapse_saas/config/plans.yaml` is the
  default catalog and `src/synapse_saas/migrations/` (with its own
  `alembic.ini`, `script_location = %(here)s`) holds the migrations. Both are
  resolved with `importlib.resources`; `REPO_ROOT` is gone. The repo-root
  `config/plans.yaml` is the file you edit here and a unit test keeps it
  identical to the packaged copy; `database/alembic.ini` is a shim for repo
  tooling that points at the packaged scripts.
- **`synapse-cli migrate` works from any directory** — it loads the packaged
  Alembic config. Products with their own tables run Alembic against a second
  branch that `depends_on` the framework head (the scaffold generates it).
- **The test plugin is public.** `synapse_saas.testing.fixtures` provides
  `migrated_db`, `clean_db`, `app`, `client`, `org_and_tokens`, the owner
  engine helpers and the platform-operator helpers. The framework's own suite
  consumes it through `tests/conftest.py`, so it cannot drift from what the
  suite needs.
- **Products depend on the package.** The scaffold (`synapse-cli new`, P5)
  generates a project whose `pyproject.toml` depends on `synapse-saas>=X,<X+1`
  from PyPI — not a copy of the source. Publishing (PyPI trusted publishing,
  npm, Maven Central, Go tags) is the release pipeline in P6.

## Consequences

- Upgrading the framework in a product is a version bump plus
  `synapse-cli migrate`, not a merge.
- The wheel is larger by the catalog and the migration scripts (kilobytes).
- Migration numbering is a shared namespace: products never edit framework
  migrations; they add their own branch.
- Package coordinates: PyPI `synapse-saas`; the clients are `synapse-saas-client`
  (PyPI), `@synapse-saas/client` (npm), `dev.synapse:synapse-saas-client`
  (Maven), and the Go module under `sdk/go` (ADR 0012 will settle the port
  repos' names).
