"""Shared pytest fixtures.

- unit tests: no DB required
- pg-marked integration tests: compose Postgres + Alembic + per-test truncation
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_contextvars() -> None:
    """Never let one test's tenant/user context leak into the next."""
    from synapse_saas.core import context

    context._tenant.set(None)
    context._user.set(None)
    context._request_id.set(None)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "pg: integration tests requiring PostgreSQL")
