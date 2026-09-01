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


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


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


async def set_rls_tenant(session: AsyncSession, organization_id: UUID) -> None:
    """Set the transaction-local RLS tenant when SYNAPSE_TENANT_ISOLATION=app_and_rls.

    Must be called inside the active transaction. No-op otherwise.
    """
    if not get_settings().rls_enabled:
        return
    await session.execute(
        text("SELECT set_config('app.current_tenant', :org_id, true)"),
        {"org_id": str(organization_id)},
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
