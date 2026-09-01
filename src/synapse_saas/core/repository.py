"""Tenant-scoped repository base.

The framework's central security boundary: every read is filtered by the active
tenant, every write is stamped with it. Application code never writes
`WHERE organization_id = ?` — this class does, or the query doesn't happen.

Usage:
    class ProjectRepo(TenantRepository[Project]):
        model = Project

    projects = await ProjectRepo(session).list()          # tenant-filtered
    project = await ProjectRepo(session).get(project_id)  # 404 across tenants
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.dml import Delete

from synapse_saas.core.context import current_tenant
from synapse_saas.core.db import Base, TenantMixin
from synapse_saas.core.errors import NotFoundError, TenantViolationError

ModelT = TypeVar("ModelT", bound=Base)


class TenantRepository(Generic[ModelT]):
    """Auto-filtering repository for `TenantMixin` models.

    Tenant is resolved lazily per call from the request context (or passed
    explicitly for worker jobs). `is_platform=True` contexts skip filtering —
    reserved for platform-admin surfaces and system jobs.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession, *, tenant_id: UUID | None = None) -> None:
        self.session = session
        self._explicit_tenant_id = tenant_id

    @property
    def tenant_id(self) -> UUID:
        if self._explicit_tenant_id is not None:
            return self._explicit_tenant_id
        ctx = current_tenant()
        if ctx is None:
            raise TenantViolationError(
                "No tenant context active — pass tenant_id explicitly or run inside a tenant scope"
            )
        if ctx.is_platform:
            raise TenantViolationError(
                "Platform scope cannot use TenantRepository without an explicit tenant_id"
            )
        return ctx.organization_id

    def _org_column(self) -> InstrumentedAttribute[UUID]:
        col = getattr(self.model, "organization_id", None)
        if col is None:
            msg = f"{self.model.__name__} does not inherit TenantMixin"
            raise TypeError(msg)
        return col

    def _scoped(self, stmt: Select | Delete, *, explicit_org: UUID | None = None) -> Any:
        # An explicit org filter IS the scope (worker jobs, cross-org queries)
        if explicit_org is not None:
            return stmt.where(self._org_column() == explicit_org)
        ctx = current_tenant() if self._explicit_tenant_id is None else None
        if ctx is not None and ctx.is_platform:
            return stmt  # platform scope sees everything
        return stmt.where(self._org_column() == self.tenant_id)

    # ── Reads ───────────────────────────────────────────────────────────────────

    async def get(self, id_: UUID) -> ModelT | None:
        stmt = self._scoped(select(self.model).where(self.model.id == id_))  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_404(self, id_: UUID) -> ModelT:
        obj = await self.get(id_)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} not found")
        return obj

    async def list(self, *, limit: int = 50, offset: int = 0, **filters: Any) -> Sequence[ModelT]:
        explicit = filters.pop("organization_id", None)
        stmt = self._scoped(select(self.model), explicit_org=explicit)
        stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(self.model.id).limit(limit).offset(offset)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        explicit = filters.pop("organization_id", None)
        stmt = self._scoped(select(func.count()).select_from(self.model), explicit_org=explicit)
        stmt = self._apply_filters(stmt, filters)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def exists(self, **filters: Any) -> bool:
        return await self.count(**filters) > 0

    async def first(self, **filters: Any) -> ModelT | None:
        explicit = filters.pop("organization_id", None)
        stmt = self._scoped(select(self.model), explicit_org=explicit)
        stmt = self._apply_filters(stmt, filters).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    # ── Writes ──────────────────────────────────────────────────────────────────

    async def add(self, obj: ModelT) -> ModelT:
        """Stamp the tenant and add. Objects already stamped with another org raise."""
        if not isinstance(obj, TenantMixin):
            msg = f"{type(obj).__name__} does not inherit TenantMixin"
            raise TypeError(msg)
        incoming = getattr(obj, "organization_id", None)
        if incoming is not None and incoming != self.tenant_id:
            raise TenantViolationError(
                f"Cannot attach {type(obj).__name__} to organization {incoming} "
                f"while operating as tenant {self.tenant_id}"
            )
        obj.organization_id = self.tenant_id
        self.session.add(obj)
        return obj

    async def add_many(self, objs: list[ModelT]) -> list[ModelT]:
        return [await self.add(obj) for obj in objs]

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)

    async def delete_where(self, **filters: Any) -> int:
        explicit = filters.pop("organization_id", None)
        stmt = self._apply_filters(self._scoped(delete(self.model), explicit_org=explicit), filters)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    # ── Helpers ─────────────────────────────────────────────────────────────────

    def _apply_filters(self, stmt: Any, filters: dict[str, Any]) -> Any:
        for attr, value in filters.items():
            if value is None:
                continue
            col = getattr(self.model, attr, None)
            if col is None:
                msg = f"{self.model.__name__} has no column {attr!r}"
                raise ValueError(msg)
            stmt = stmt.where(col == value)
        return stmt


class Repository(Generic[ModelT]):
    """Unscoped repository for global models (users, plans, system roles).

    Exists so global entities get the same repo ergonomics without pretending
    to be tenant-scoped.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: UUID) -> ModelT | None:
        result = await self.session.execute(select(self.model).where(self.model.id == id_))  # type: ignore[attr-defined]
        return result.scalar_one_or_none()

    async def get_or_404(self, id_: UUID) -> ModelT:
        obj = await self.get(id_)
        if obj is None:
            raise NotFoundError(f"{self.model.__name__} not found")
        return obj

    async def list(self, *, limit: int = 50, offset: int = 0, **filters: Any) -> Sequence[ModelT]:
        stmt = self._apply_filters(select(self.model), filters).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = self._apply_filters(select(func.count()).select_from(self.model), filters)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def first(self, **filters: Any) -> ModelT | None:
        stmt = self._apply_filters(select(self.model), filters).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)

    def _apply_filters(self, stmt: Any, filters: dict[str, Any]) -> Any:
        for attr, value in filters.items():
            if value is None:
                continue
            col = getattr(self.model, attr, None)
            if col is None:
                msg = f"{self.model.__name__} has no column {attr!r}"
                raise ValueError(msg)
            stmt = stmt.where(col == value)
        return stmt
