"""Agent registry service.

CRUD over org-scoped agents with lifecycle events through the outbox.
Every mutation emits its event INSIDE the transaction (webhooks fan out
via the worker); every read is tenant-filtered by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.agents.models import Agent
from synapse_saas.audit.service import AuditService
from synapse_saas.core import events
from synapse_saas.core.errors import ConflictError, NotFoundError
from synapse_saas.core.outbox import append_outbox


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_org(self, organization_id: UUID, *, include_deleted: bool = False) -> list[Agent]:
        stmt = select(Agent).where(Agent.organization_id == organization_id)
        if not include_deleted:
            stmt = stmt.where(Agent.deleted_at.is_(None))
        stmt = stmt.order_by(Agent.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, agent_id: UUID, organization_id: UUID) -> Agent:
        agent = await self._get_scoped(agent_id, organization_id)
        return agent

    async def create(
        self,
        organization_id: UUID,
        *,
        slug: str,
        name: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> Agent:
        existing = await self._by_slug(organization_id, slug, include_deleted=True)
        if existing is not None:
            raise ConflictError(
                f"An agent with slug {slug!r} already exists in this organization",
                extras={"slug": slug},
            )

        agent = Agent(
            id=uuid4(),
            organization_id=organization_id,
            slug=slug,
            name=name,
            description=description,
            config=config or {},
        )
        self.session.add(agent)
        await self.session.flush()
        await self.session.refresh(agent)  # server-defaulted attrs must not lazy-fire in serialization

        append_outbox(
            self.session,
            event_type=events.AGENT_REGISTERED,
            aggregate_type="agent",
            aggregate_id=agent.id,
            organization_id=organization_id,
            payload={"slug": agent.slug, "name": agent.name},
        )
        AuditService(self.session).log(
            "agent.registered",
            organization_id=organization_id,
            target_type="agent",
            target_id=agent.id,
            diff={"slug": agent.slug, "name": agent.name},
        )
        return agent

    async def update(
        self,
        agent_id: UUID,
        organization_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> Agent:
        agent = await self._get_scoped(agent_id, organization_id)
        diff: dict[str, Any] = {}
        if name is not None and name != agent.name:
            diff["name"] = {"from": agent.name, "to": name}
            agent.name = name
        if description is not None and description != agent.description:
            diff["description"] = {"from": agent.description, "to": description}
            agent.description = description
        if config is not None and config != agent.config:
            diff["config"] = "updated"
            agent.config = config
        if diff:
            await self.session.flush()
            # JSONB mutations expire attributes at the asyncpg boundary;
            # re-load so response serialization never lazy-fires IO.
            await self.session.refresh(agent)
            append_outbox(
                self.session,
                event_type=events.AGENT_UPDATED,
                aggregate_type="agent",
                aggregate_id=agent.id,
                organization_id=organization_id,
                payload={"slug": agent.slug, "changed": sorted(diff)},
            )
            AuditService(self.session).log(
                "agent.updated",
                organization_id=organization_id,
                target_type="agent",
                target_id=agent.id,
                diff=diff,
            )
        return agent

    async def set_status(self, agent_id: UUID, organization_id: UUID, *, status: str) -> Agent:
        if status not in ("active", "disabled"):
            raise NotFoundError("Unknown status")
        agent = await self._get_scoped(agent_id, organization_id)
        if agent.status == status:
            return agent

        agent.status = status
        await self.session.flush()
        await self.session.refresh(agent)  # onupdate-expired attrs must not lazy-fire in serialization

        event_type = events.AGENT_DISABLED if status == "disabled" else events.AGENT_UPDATED
        append_outbox(
            self.session,
            event_type=event_type,
            aggregate_type="agent",
            aggregate_id=agent.id,
            organization_id=organization_id,
            payload={"slug": agent.slug, "status": status},
        )
        AuditService(self.session).log(
            f"agent.{status}",
            organization_id=organization_id,
            target_type="agent",
            target_id=agent.id,
            diff={"status": status},
        )
        return agent

    async def delete(self, agent_id: UUID, organization_id: UUID) -> None:
        """Soft delete: registry rows are billing history; never hard-removed."""
        agent = await self._get_scoped(agent_id, organization_id)
        agent.deleted_at = datetime.now(UTC)
        agent.status = "disabled"
        await self.session.flush()
        append_outbox(
            self.session,
            event_type=events.AGENT_DISABLED,
            aggregate_type="agent",
            aggregate_id=agent.id,
            organization_id=organization_id,
            payload={"slug": agent.slug, "deleted": True},
        )
        AuditService(self.session).log(
            "agent.deleted",
            organization_id=organization_id,
            target_type="agent",
            target_id=agent.id,
            diff={},
        )

    async def _get_scoped(self, agent_id: UUID, organization_id: UUID) -> Agent:
        agent = (
            await self.session.execute(
                select(Agent).where(
                    Agent.id == agent_id,
                    Agent.organization_id == organization_id,
                    Agent.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise NotFoundError("Agent not found", extras={"agent_id": str(agent_id)})
        return agent

    async def _by_slug(
        self, organization_id: UUID, slug: str, *, include_deleted: bool = False
    ) -> Agent | None:
        stmt = select(Agent).where(Agent.organization_id == organization_id, Agent.slug == slug)
        if not include_deleted:
            stmt = stmt.where(Agent.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()
