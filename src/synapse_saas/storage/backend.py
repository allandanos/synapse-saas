"""Storage backends: S3-compatible (aioboto3) or local disk.

Both enforce org-scoped keys — `{org_id}/…` — the tenant boundary for files.
A key from another org is a 404, exactly like rows.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import NotFoundError, StorageError, TenantViolationError
from synapse_saas.core.logging import get_logger

logger = get_logger(__name__)

_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,500}$")


def validate_key(key: str, *, organization_id: UUID | None = None) -> None:
    """Keys are `{org_id}/path`. Reject malformed or cross-org keys."""
    if not key or not _KEY_RE.match(key):
        raise StorageError("Invalid storage key")
    if organization_id is not None:
        expected_prefix = f"{organization_id}/"
        if not key.startswith(expected_prefix):
            raise TenantViolationError(
                f"Storage key must be prefixed with the organization id ({expected_prefix})"
            )


def scoped_key(organization_id: UUID, name: str) -> str:
    """Build a validated org-scoped key from a caller-supplied object name."""
    safe_name = name.lstrip("/")
    # nested paths allowed, but no traversal
    if "/" in safe_name and ".." in safe_name.split("/"):
        raise StorageError("Invalid storage key")
    key = f"{organization_id}/{safe_name}"
    validate_key(key, organization_id=organization_id)
    return key


class S3Storage:
    """Any S3-compatible target: AWS S3, Cloudflare R2, MinIO."""

    def __init__(self) -> None:
        import aioboto3  # imported lazily: heavy session object

        settings = get_settings()
        if not settings.s3_bucket:
            raise StorageError("SYNAPSE_S3_BUCKET is not configured")
        self._session = aioboto3.Session()
        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint_url or None
        self._region = settings.s3_region
        self._presign = settings.storage_presign_seconds

    def _client_kwargs(self) -> dict[str, Any]:
        settings = get_settings()
        kwargs: dict[str, Any] = {
            "region_name": self._region,
            "aws_access_key_id": settings.s3_access_key_id or None,
            "aws_secret_access_key": settings.s3_secret_access_key or None,
        }
        if self._endpoint:
            kwargs["endpoint_url"] = self._endpoint
        return kwargs

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        validate_key(key)
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return key

    async def get(self, *, key: str) -> bytes:
        validate_key(key)
        try:
            async with self._session.client("s3", **self._client_kwargs()) as s3:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
                body = await response["Body"].read()
                return bytes(body)
        except Exception as exc:
            if "NoSuchKey" in str(exc) or "404" in str(exc):
                raise NotFoundError("Object not found") from exc
            raise StorageError(f"S3 get failed: {exc}") from exc

    async def delete(self, *, key: str) -> None:
        validate_key(key)
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def presign_get(self, *, key: str) -> str:
        """Time-limited download URL — the preferred way to serve files."""
        validate_key(key)
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._presign,
            )
            return url

    async def presign_put(self, *, key: str, content_type: str) -> str:
        """Time-limited upload URL — large files bypass the API entirely."""
        validate_key(key)
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            url: str = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=self._presign,
            )
            return url


class LocalDiskStorage:
    """Zero-config fallback: files under SYNAPSE_STORAGE_ROOT/{org_id}/…."""

    def __init__(self) -> None:
        self._root = Path(get_settings().storage_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if not str(path).startswith(str(self._root)):
            raise StorageError("Invalid storage key")  # traversal guard
        return path

    async def put(self, *, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return key

    async def get(self, *, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise NotFoundError("Object not found")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, *, key: str) -> None:
        path = self._path(key)

        def _remove() -> None:
            path.unlink(missing_ok=True)

        await asyncio.to_thread(_remove)

    async def presign_get(self, *, key: str) -> str:
        """Local mode has no presigned URLs — callers stream via the API."""
        self._path(key)  # validation still applies
        raise StorageError("Presigned URLs require an S3-compatible backend")

    async def presign_put(self, *, key: str, content_type: str) -> str:
        self._path(key)
        raise StorageError("Presigned URLs require an S3-compatible backend")


_backend: S3Storage | LocalDiskStorage | None = None


def get_storage() -> S3Storage | LocalDiskStorage:
    """S3 when a bucket is configured; local disk otherwise (clone-and-run)."""
    global _backend
    if _backend is None:
        settings = get_settings()
        if settings.s3_bucket:
            logger.info("storage_backend", backend="s3", bucket=settings.s3_bucket)
            _backend = S3Storage()
        else:
            logger.info("storage_backend", backend="local", root=settings.storage_root)
            _backend = LocalDiskStorage()
    return _backend


def reset_storage() -> None:
    """Test hook: drop the cached backend after settings change."""
    global _backend
    _backend = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "LocalDiskStorage",
    "S3Storage",
    "get_storage",
    "now_iso",
    "reset_storage",
    "scoped_key",
    "validate_key",
]
