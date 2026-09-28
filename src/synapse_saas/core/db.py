"""Database engine, declarative base, and mixins.

- Naming convention pinned so Alembic-generated constraints are deterministic.
- `TenantMixin` is the multi-tenancy primitive: any model inheriting it is
  organization-scoped and safe to use with `TenantRepository`.
- `get_session` commits on success; `DomainError` inside a request rolls back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ForeignKey, MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import DomainError

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_owner_engine: AsyncEngine | None = None
_owner_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def get_engine() -> AsyncEngine:
    """The request engine: connects as SYNAPSE_DATABASE_URL (RLS-subject role when RLS is on)."""
    global _engine
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
    return _engine


def get_owner_engine() -> AsyncEngine:
    """The schema-owner engine for the worker, CLI, and migrations (bypasses RLS).

    Falls back to the request engine when SYNAPSE_WORKER_DATABASE_URL is unset,
    so single-role deployments keep one pool.
    """
    global _owner_engine
    settings = get_settings()
    if not settings.worker_database_url:
        return get_engine()
    if _owner_engine is None:
        _owner_engine = _make_engine(settings.worker_database_url)
    return _owner_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def get_owner_session_factory() -> async_sessionmaker[AsyncSession]:
    """Sessions that must see every tenant: worker jobs, seeds, CLI. Never used by the API."""
    global _owner_session_factory
    if not get_settings().worker_database_url:
        return get_session_factory()
    if _owner_session_factory is None:
        _owner_session_factory = async_sessionmaker(
            get_owner_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _owner_session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory, _owner_engine, _owner_session_factory
    if _engine is not None:
        await _engine.dispose()
    if _owner_engine is not None:
        await _owner_engine.dispose()
    _engine = None
    _session_factory = None
    _owner_engine = None
    _owner_session_factory = None


class Base(DeclarativeBase):
    metadata = metadata


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False, sort_order=1000)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False, sort_order=1001
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, sort_order=1002)


class TenantMixin:
    """Marks a model as organization-scoped.

    `TenantRepository` reads this to auto-filter reads and auto-inject writes.
    The FK cascade means deleting an org removes its data in one statement.
    """

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        sort_order=-100,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── Row-level security GUCs ────────────────────────────────────────────────────
# Policies (migration 0013) admit a row when ANY of these hold:
#   organization_id = app.current_tenant      (set after tenant resolution)
#   app.rls_platform = 'on'                   (platform-admin surfaces)
#   user_id = app.current_user                (memberships/overrides: pre-tenant
#                                              reads of a user's own rows)
#   organization_id IS NULL                   (platform-scope rows, where allowed)
# All three are transaction-local (`set_config(..., true)`) so pooled
# connections never leak a tenant between requests. Every helper is a no-op
# unless SYNAPSE_TENANT_ISOLATION=app_and_rls.


async def _set_guc(session: AsyncSession, name: str, value: str) -> None:
    await session.execute(text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value})


async def set_rls_tenant(session: AsyncSession, organization_id: UUID) -> None:
    """Bind the request transaction to one tenant. Call before the first tenant-scoped query."""
    if not get_settings().rls_enabled:
        return
    await _set_guc(session, "app.current_tenant", str(organization_id))


async def set_rls_user(session: AsyncSession, user_id: UUID) -> None:
    """Bind the authenticated user so their own memberships/overrides are readable pre-tenant."""
    if not get_settings().rls_enabled:
        return
    await _set_guc(session, "app.current_user", str(user_id))


async def set_rls_platform(session: AsyncSession) -> None:
    """Platform-admin scope: policies admit every row for this transaction."""
    if not get_settings().rls_enabled:
        return
    await _set_guc(session, "app.rls_platform", "on")


# Credential tables looked up by secret hash BEFORE any tenant context exists;
# the hash is the authorization. Everything else with organization_id is policed
# (tests/integration/test_rls_enforcement.py asserts pg_policies matches).
RLS_EXCLUDED_TABLES: frozenset[str] = frozenset({"api_keys", "refresh_tokens"})

APP_ROLE_NAME_RE = r"^[a-z_][a-z0-9_]{0,62}$"


async def provision_app_role(engine: AsyncEngine, role: str, password: str) -> None:
    """Create or refresh the RLS-subject login role the API connects as.

    Must run as the schema owner. The role is LOGIN NOBYPASSRLS NOINHERIT, owns
    nothing, gets DML on every current table/sequence, and default privileges
    for tables created by future migrations.
    """
    import re

    if not re.match(APP_ROLE_NAME_RE, role):
        raise ValueError(f"role must match {APP_ROLE_NAME_RE}, got {role!r}")
    async with engine.begin() as conn:
        # DDL takes no bind params: carry the password in a transaction-local
        # GUC and quote it with format(%L) inside the DO block.
        await conn.execute(text("SELECT set_config('synapse.provision_pw', :pw, true)"), {"pw": password})
        await conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                        EXECUTE format('CREATE ROLE {role} LOGIN NOBYPASSRLS NOINHERIT PASSWORD %L',
                                       current_setting('synapse.provision_pw'));
                    ELSE
                        EXECUTE format('ALTER ROLE {role} LOGIN NOBYPASSRLS NOINHERIT PASSWORD %L',
                                       current_setting('synapse.provision_pw'));
                    END IF;
                END $$
                """  # noqa: S608 — `role` is validated against APP_ROLE_NAME_RE above
            )
        )
        for stmt in (
            f"GRANT USAGE ON SCHEMA public TO {role}",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}",
        ):
            await conn.execute(text(stmt))


class RoleIsolationMismatchError(RuntimeError):
    """The connected DB role and SYNAPSE_TENANT_ISOLATION contradict each other."""


async def assert_role_matches_isolation() -> None:
    """Fail fast when RLS would be a lie (bypassing role) or a lockout (subject role, RLS off).

    - app_and_rls + superuser/BYPASSRLS/table-owner role ⇒ policies never apply;
      the deployment believes it has defense-in-depth and does not.
    - app + a role that is subject to policies ⇒ every tenant query returns
      zero rows because no GUC is ever set.
    """
    settings = get_settings()
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT r.rolsuper,
                           r.rolbypassrls,
                           COALESCE(
                               (SELECT bool_and(t.tableowner = current_user)
                                FROM pg_tables t WHERE t.schemaname = 'public'),
                               true
                           ) AS owns_tables,
                           current_user AS role_name
                    FROM pg_roles r
                    WHERE r.rolname = current_user
                    """
                )
            )
        ).one()
    bypasses = bool(row.rolsuper or row.rolbypassrls or row.owns_tables)
    if settings.rls_enabled and bypasses:
        raise RoleIsolationMismatchError(
            f"SYNAPSE_TENANT_ISOLATION=app_and_rls but DB role {row.role_name!r} bypasses RLS "
            "(superuser, BYPASSRLS, or table owner). Connect the API as a subject role: "
            "synapse-cli db provision-app-role"
        )
    if not settings.rls_enabled and not bypasses:
        raise RoleIsolationMismatchError(
            f"SYNAPSE_TENANT_ISOLATION=app but DB role {row.role_name!r} is subject to RLS policies; "
            "every tenant query would return zero rows. Set app_and_rls or connect as the owner."
        )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request.

    DomainError → rollback (the exception handler still renders the problem doc).
    Any other exception → rollback and re-raise for the 500 handler.
    """
    session = get_session_factory()()
    try:
        yield session
    except DomainError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    else:
        await session.commit()
