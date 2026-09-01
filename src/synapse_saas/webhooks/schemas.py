"""Webhook API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WebhookEndpointCreate(BaseModel):
    url: HttpUrl
    events: list[str] = Field(default_factory=list)  # empty ⇒ all events
    description: str | None = None


class WebhookEndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    description: str | None
    events: list[str]
    is_active: bool
    created_at: datetime


class WebhookEndpointCreated(WebhookEndpointRead):
    """Secret appears exactly once, at creation."""

    secret: str


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None
    last_response_code: int | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
