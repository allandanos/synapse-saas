"""Integration fixtures come from the public plugin (`synapse_saas.testing`).

This module only re-exports the helpers so existing imports keep working:

    from tests.integration.conftest import owner_session_factory, grant_as_platform
"""

from __future__ import annotations

from synapse_saas.testing.fixtures import (
    DEFAULT_TEST_DATABASE_URL,
    PLATFORM_ADMIN_EMAIL,
    PLATFORM_ADMIN_PASSWORD,
    database_url,
    grant_as_platform,
    org_headers,
    owner_database_url,
    owner_engine,
    owner_session_factory,
    pay_as_platform,
    platform_admin_headers,
    void_as_platform,
)

__all__ = [
    "DEFAULT_TEST_DATABASE_URL",
    "PLATFORM_ADMIN_EMAIL",
    "PLATFORM_ADMIN_PASSWORD",
    "database_url",
    "grant_as_platform",
    "org_headers",
    "owner_database_url",
    "owner_engine",
    "owner_session_factory",
    "pay_as_platform",
    "platform_admin_headers",
    "void_as_platform",
]
