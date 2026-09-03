"""hello-saas: a complete domain app on the framework.

Projects CRUD — multi-tenant, permission-checked, feature-gated, plan-limited,
metered, and audited. This file is the entire application; everything else is
framework infrastructure.

Run:
    uv run uvicorn examples.hello_saas.main:app --port 8020
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.api.app import create_app
from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.core.db import Base, TenantMixin, get_session
from synapse_saas.core.repository import TenantRepository
from synapse_saas.identity.dependencies import CurrentUser
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.usage.service import UsageService

# ── Domain model: one line of tenancy ─────────────────────────────────────────


class Project(TenantMixin, Base):
    __tablename__ = "example_projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(nullable=False)


class ProjectRepository(TenantRepository[Project]):
    model = Project


# ── API ───────────────────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    organization_id: uuid.UUID


router = APIRouter(prefix="/projects", tags=["projects"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[ProjectRead])
async def list_projects(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> list[ProjectRead]:
    await require_permission("project:read", user, session, tenant)
    projects = await ProjectRepository(session).list(limit=100)
    return [ProjectRead.model_validate(p) for p in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> ProjectRead:
    await require_permission("project:manage", user, session, tenant)

    # Gauge limit: the `projects` cap from the org's plan (402 on breach,
    # with upgrade hints — enforced inside this transaction).
    repo = ProjectRepository(session)
    current = await repo.count()
    await UsageService(session).ensure_gauge_capacity(
        tenant.organization_id, "projects", current=current, adding=1
    )

    # Meter the create, then write — both commit together.
    await UsageService(session).record(tenant.organization_id, "projects", quantity=1)
    project = await repo.add(Project(title=body.title))
    await session.flush()  # populate defaults (id) before serialization
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> None:
    await require_permission("project:manage", user, session, tenant)
    repo = ProjectRepository(session)
    project = await repo.get_or_404(project_id)  # 404 cross-tenant
    await repo.delete(project)


def create_example_app() -> FastAPI:
    """Framework app factory + this domain's router."""
    app = create_app()
    app.include_router(router)
    return app


app = create_example_app()
