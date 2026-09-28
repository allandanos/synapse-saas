"""Storage API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileUploadRequest(BaseModel):
    name: str  # object name within the org namespace; nested paths allowed


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    key: str
    name: str
    content_type: str
    size_bytes: int
    status: str = "ready"
    created_at: datetime


class PresignUploadRequest(BaseModel):
    """Reserve quota + get a PUT URL for an object the client uploads directly."""

    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field("application/octet-stream", max_length=128)
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024 * 1024)  # single PUT ceiling


class PresignUploadResponse(BaseModel):
    id: uuid.UUID
    key: str
    url: str
    method: str = "PUT"
    headers: dict[str, str]
    expires_in: int


class PresignResponse(BaseModel):
    url: str
    key: str
    expires_in: int
