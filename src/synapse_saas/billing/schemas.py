"""Billing API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckoutRequest(BaseModel):
    plan_key: str


class CheckoutResponse(BaseModel):
    url: str | None
    provider: str
    manual_instructions: str | None = None


class PortalUrlResponse(BaseModel):
    url: str | None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str | None
    currency: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    status: str
    period_start: datetime | None
    period_end: datetime | None
    hosted_url: str | None
    issued_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
