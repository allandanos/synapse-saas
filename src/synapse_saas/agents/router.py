"""Agent registry endpoints.

Entitlement-gated (`agents` feature key — AI Agents is a paid plan line) and
permission-gated (agents:read / agents:manage), tenant-scoped by construction.
See ADR 0007: governance and billing only, no execution endpoints here.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from synapse_saas.agents.schemas import AgentCreate, AgentRead, AgentUpdate
from synapse_saas.agents.service import AgentService
from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.core.pagination import PageDep, paginate_in_memory
from synapse_saas.entitlements.dependencies import require_feature
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import TenantDep

# Every agents route is behind the `agents` entitlement (403 + upgrade hints
# for plans without it) — one declaration, not one call per handler.
router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(require_feature("agents"))],
)


@router.get("", response_model=list[AgentRead])
async def list_agents(
    tenant: TenantDep, session: SessionDep, user: CurrentUser, page: PageDep, response: Response
) -> list[AgentRead]:
    await require_permission("agents:read", user, session, tenant)
    agents = await AgentService(session).list_for_org(tenant.organization_id)
    return [AgentRead.model_validate(a) for a in paginate_in_memory(agents, page, response)]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> AgentRead:
    await require_permission("agents:manage", user, session, tenant)
    agent = await AgentService(session).create(
        tenant.organization_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        config=body.config,
    )
    return AgentRead.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> AgentRead:
    await require_permission("agents:read", user, session, tenant)
    agent = await AgentService(session).get(agent_id, tenant.organization_id)
    return AgentRead.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: UUID,
    body: AgentUpdate,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> AgentRead:
    await require_permission("agents:manage", user, session, tenant)
    agent = await AgentService(session).update(
        agent_id,
        tenant.organization_id,
        name=body.name,
        description=body.description,
        config=body.config,
    )
    return AgentRead.model_validate(agent)


@router.post("/{agent_id}/disable", response_model=AgentRead)
async def disable_agent(
    agent_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> AgentRead:
    await require_permission("agents:manage", user, session, tenant)
    agent = await AgentService(session).set_status(agent_id, tenant.organization_id, status="disabled")
    return AgentRead.model_validate(agent)


@router.post("/{agent_id}/enable", response_model=AgentRead)
async def enable_agent(
    agent_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> AgentRead:
    await require_permission("agents:manage", user, session, tenant)
    agent = await AgentService(session).set_status(agent_id, tenant.organization_id, status="active")
    return AgentRead.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> None:
    await require_permission("agents:manage", user, session, tenant)
    await AgentService(session).delete(agent_id, tenant.organization_id)
