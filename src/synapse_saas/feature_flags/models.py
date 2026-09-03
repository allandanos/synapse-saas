"""Feature flag model.

Flags are deployment-level toggles — distinct from plan entitlements:
- entitlements answer "what did this org pay for?"
- flags answer "is this code path on yet?" (rollouts, kill switches,
  opt-in betas independent of billing)

Resolution order (first match wins):
  user override → org override → global default
Percentage rollouts bucket deterministically on (flag, org) or (flag, user).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.core.db import Base, TimestampMixin

ROLLOUT_PERCENT_MIN = 0
ROLLOUT_PERCENT_MAX = 100


class FeatureFlag(Base, TimestampMixin):
    """Global flag definition + default state."""

    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # None ⇒ fully controlled by overrides/rollout; absent everything ⇒ off
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollout_percentage: Mapped[int | None] = mapped_column(
        Integer,
        CheckConstraint(
            "rollout_percentage IS NULL OR (rollout_percentage BETWEEN 0 AND 100)",
            name="ck_feature_flags_rollout",
        ),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeatureFlagOverride(Base, TimestampMixin):
    """Org- or user-level override of a flag. User beats org."""

    __tablename__ = "feature_flag_overrides"
    __table_args__ = (
        CheckConstraint(
            "organization_id IS NOT NULL OR user_id IS NOT NULL",
            name="ck_ff_override_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    flag_key: Mapped[str] = mapped_column(
        String(100), ForeignKey("feature_flags.key", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
