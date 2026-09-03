"""Alembic environment — async engine against SYNAPSE_DATABASE_URL."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from synapse_saas.core.config import get_settings
from synapse_saas.core.db import Base

# Import every module with models so Base.metadata is complete
from synapse_saas import (  # noqa: F401
    api_keys,
    audit,
    authorization,
    billing,
    entitlements,
    identity,
    storage,
    subscriptions,
    tenancy,
    usage,
    webhooks,
)
from synapse_saas.api_keys import models as _api_keys_models  # noqa: F401
from synapse_saas.audit import models as _audit_models  # noqa: F401
from synapse_saas.authorization import models as _authz_models  # noqa: F401
from synapse_saas.billing import models as _billing_models  # noqa: F401
from synapse_saas.entitlements import models as _entl_models  # noqa: F401
from synapse_saas.identity import models as _identity_models  # noqa: F401
from synapse_saas.storage import models as _storage_models  # noqa: F401
from synapse_saas.subscriptions import models as _sub_models  # noqa: F401
from synapse_saas.tenancy import models as _tenancy_models  # noqa: F401
from synapse_saas.usage import models as _usage_models  # noqa: F401
from synapse_saas.webhooks import models as _webhook_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
