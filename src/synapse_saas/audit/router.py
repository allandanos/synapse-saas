"""Audit log endpoints (org-scoped, filtered)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from synapse_saas.audit.schemas import AuditEntryRead, AuditPage
from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.tenancy.dependencies import TenantDep

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditPage)
async def list_audit(
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
    event_type: str | None = None,
    actor_user_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AuditPage:
    await require_permission("audit:read", user, session, tenant)
    from sqlalchemy import select

    from synapse_saas.audit.models import AuditLog

    where = [AuditLog.organization_id == tenant.organization_id]
    if event_type:
        where.append(AuditLog.event_type == event_type)
    if actor_user_id:
        where.append(AuditLog.actor_user_id == actor_user_id)

    rows = (
        (
            await session.execute(
                select(AuditLog)
                .where(*where)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return AuditPage(data=[AuditEntryRead.model_validate(r) for r in rows])
