"""Public pytest plugin for framework consumers.

A product built on the framework gets the same integration fixtures the
framework's own suite runs on — a migrated scratch database, per-test
truncation, a booted app, an HTTP client, an org with tokens, and platform-
operator helpers — by adding one line to its root conftest.py:

    pytest_plugins = ["synapse_saas.testing.fixtures"]

The framework's own tests consume the plugin the same way, so it cannot drift
from what the suite actually needs (ADR 0011).
"""

from __future__ import annotations

__all__ = ["fixtures"]
