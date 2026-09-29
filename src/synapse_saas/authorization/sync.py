"""Tuple sync: RBAC (source of truth) → OpenFGA relationship tuples (ADR 0009).

Request side: `queue_tuple_sync()` appends an internal outbox event in the
mutating transaction. Worker side: `apply_tuple_sync()` recomputes the
member's desired tuples from the database and writes/deletes the difference.
The outbox carries retries and dead-lettering, so no request ever waits on
OpenFGA and a transient outage is replayed, not lost.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from synapse_saas.authorization.fga import FgaClient, Tuple
from synapse_saas.authorization.fga_model import ROLE_ORDER, relation_for
from synapse_saas.core import events
from synapse_saas.core.config import get_settings
from synapse_saas.core.ids import uuid_v7
from synapse_saas.core.logging import get_logger
from synapse_saas.core.outbox import append_outbox

logger = get_logger(__name__)


def user_object(user_id: UUID | str) -> str:
    return f"user:{user_id}"


def org_object(organization_id: UUID | str) -> str:
    return f"organization:{organization_id}"


def desired_tuples(
    *, user_id: UUID | str, organization_id: UUID | str, role_keys: list[str], permission_keys: list[str]
) -> set[Tuple]:
    """What OpenFGA must hold for one active member.

    System roles map to role relations (the model derives their permissions);
    permissions that come from custom roles only are written as direct
    `can_*` tuples so the model needs no per-tenant relations.
    """
    org = org_object(organization_id)
    user = user_object(user_id)
    tuples: set[Tuple] = set()
    system_roles = [key for key in role_keys if key in ROLE_ORDER]
    for role in system_roles:
        tuples.add(Tuple(user, role, org))
    from synapse_saas.authorization.permissions import SYSTEM_ROLES

    covered: set[str] = set()
    for role in system_roles:
        covered.update(SYSTEM_ROLES[role]["permissions"])  # type: ignore[arg-type]
    for perm in permission_keys:
        if perm not in covered:
            tuples.add(Tuple(user, relation_for(perm), org))
    return tuples


def queue_tuple_sync(session: AsyncSession, *, organization_id: UUID, user_id: UUID | None) -> None:
    """Record that this member's tuples must be recomputed (no-op without OpenFGA)."""
    if user_id is None or get_settings().authz_backend != "openfga":
        logger.debug("fga_sync_not_queued", backend=get_settings().authz_backend, user=str(user_id))
        return
    payload = {"organization_id": str(organization_id), "user_id": str(user_id)}
    append_outbox(
        session,
        event_type=events.AUTHZ_TUPLES_CHANGED,
        aggregate_type="membership",
        aggregate_id=uuid_v7(),
        organization_id=organization_id,
        payload=payload,
    )
    # Converge eagerly once the rows are durable: without this the member who
    # just gained a role is denied for the dispatch interval plus the decision
    # cache TTL. The outbox event still guarantees convergence (retries,
    # dead-lettering); the worker's pass then finds an empty diff.
    from synapse_saas.core.cache import defer_after_commit

    defer_after_commit(session, lambda: apply_tuple_sync(payload), name="fga_tuple_sync")


async def apply_tuple_sync(payload: dict[str, Any], *, client: FgaClient | None = None) -> dict[str, int]:
    """Worker side: converge OpenFGA to the member's current RBAC state."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from synapse_saas.core.db import get_owner_session_factory
    from synapse_saas.tenancy.models import Membership

    org_id = UUID(str(payload["organization_id"]))
    user_id = UUID(str(payload["user_id"]))
    client = client or FgaClient()
    if not client.configured:
        logger.warning("fga_sync_skipped_unconfigured", org=str(org_id), user=str(user_id))
        return {"writes": 0, "deletes": 0}

    async with get_owner_session_factory()() as session:
        membership = (
            await session.execute(
                select(Membership)
                .options(selectinload(Membership.roles))
                .where(Membership.organization_id == org_id, Membership.user_id == user_id)
            )
        ).scalar_one_or_none()
        if membership is None or membership.status != "active":
            desired: set[Tuple] = set()
        else:
            desired = desired_tuples(
                user_id=user_id,
                organization_id=org_id,
                role_keys=[r.key for r in membership.roles],
                permission_keys=list(membership.permission_keys or []),
            )

    current = {t for t in await client.read_tuples(org_object(org_id)) if t.user == user_object(user_id)}
    writes = sorted(desired - current, key=lambda t: t.relation)
    deletes = sorted(current - desired, key=lambda t: t.relation)
    await client.write(writes=writes, deletes=deletes)
    logger.info(
        "fga_tuples_synced", org=str(org_id), user=str(user_id), writes=len(writes), deletes=len(deletes)
    )
    return {"writes": len(writes), "deletes": len(deletes)}


async def handle_event(event_type: str, payload: dict[str, Any]) -> None:
    """Outbox consumer entry point (internal audience)."""
    if event_type == events.AUTHZ_TUPLES_CHANGED:
        await apply_tuple_sync(payload)
