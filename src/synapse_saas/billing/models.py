"""Billing models: customers and invoices.

Provider IDs are stored verbatim; (provider, provider_*_id) uniques make
webhook application naturally idempotent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from synapse_saas.core.db import Base, TimestampMixin


class BillingCustomer(Base, TimestampMixin):
    __tablename__ = "billing_customers"
    __table_args__ = (
        UniqueConstraint("provider", "provider_customer_id", name="uq_billing_customers_provider_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_customer_id: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(64))
    billing_address: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("provider", "provider_invoice_id", name="uq_invoices_provider_ref"),
        CheckConstraint(
            "status IN ('draft','open','paid','void','uncollectible')",
            name="ck_invoices_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    billing_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("billing_customers.id", ondelete="SET NULL")
    )
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_invoice_id: Mapped[str | None] = mapped_column(String(255))
    number: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="PHP", nullable=False)
    subtotal_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    tax_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hosted_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
