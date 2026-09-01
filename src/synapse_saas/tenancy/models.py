"""Tenancy models: organizations and memberships."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from synapse_saas.core.db import Base, SoftDeleteMixin, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from synapse_saas.identity.models import User


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("status IN ('active','suspended','archived')", name="org_status_valid"),
        default="active",
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="organization", lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization {self.slug}>"


class Membership(Base, TenantMixin, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_memberships_org_user",
        ),
        UniqueConstraint(
            "organization_id",
            "invited_email",
            name="uq_memberships_org_invited_email",
        ),
        CheckConstraint(
            "user_id IS NOT NULL OR invited_email IS NOT NULL",
            name="ck_memberships_user_or_invite",
        ),
        CheckConstraint(
            "status IN ('invited','active','suspended')",
            name="ck_memberships_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    invited_email: Mapped[str | None] = mapped_column(CITEXT)
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="invited", nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Denormalized permission set for cheap authz checks (maintained on write)
    permission_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, nullable=False, server_default=text("'{}'")
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User | None] = relationship(back_populates="memberships", lazy="selectin")
    roles: Mapped[list[AuthorizationRole]] = relationship(
        secondary="membership_roles", lazy="selectin", viewonly=True
    )

    @property
    def is_owner(self) -> bool:
        return "owner" in {r.key for r in self.roles} if self.roles else False


# Forward reference resolved after authorization.models defines AuthorizationRole
from synapse_saas.authorization.models import AuthorizationRole  # noqa: E402
