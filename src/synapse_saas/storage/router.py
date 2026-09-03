"""File storage endpoints.

Upload/download is feature-gated on `api_access` (storage ships on paid tiers)
and meters `storage_bytes` against the plan quota — the same enforcement path
as every other metered resource.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from starlette.datastructures import UploadFile

from synapse_saas.authorization.dependencies import require_permission
from synapse_saas.core.errors import NotFoundError, StorageError
from synapse_saas.entitlements.service import EntitlementService
from synapse_saas.identity.dependencies import CurrentUser, SessionDep
from synapse_saas.storage.backend import get_storage, scoped_key
from synapse_saas.storage.models import StoredFile
from synapse_saas.storage.schemas import FileRead, PresignResponse
from synapse_saas.tenancy.dependencies import TenantDep
from synapse_saas.usage.service import UsageService

router = APIRouter(prefix="/files", tags=["files"])

MAX_DIRECT_UPLOAD_BYTES = 10 * 1024 * 1024  # larger ⇒ presigned PUT


@router.get("", response_model=list[FileRead])
async def list_files(tenant: TenantDep, session: SessionDep, user: CurrentUser) -> list[FileRead]:
    await require_permission("file:read", user, session, tenant)
    from sqlalchemy import select

    rows = (
        (
            await session.execute(
                select(StoredFile)
                .where(StoredFile.organization_id == tenant.organization_id, StoredFile.deleted_at.is_(None))
                .order_by(StoredFile.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [FileRead.model_validate(r) for r in rows]


@router.post("", response_model=FileRead, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    tenant: TenantDep,
    session: SessionDep,
    user: CurrentUser,
) -> FileRead:
    """Direct upload (multipart, ≤10 MiB). Larger files use the presigned flow."""
    await require_permission("file:write", user, session, tenant)
    await EntitlementService(session).require_feature(tenant.organization_id, "api_access")

    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise StorageError("Expected multipart/form-data upload")

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise StorageError("Missing 'file' part")
    data = await upload.read()
    if len(data) > MAX_DIRECT_UPLOAD_BYTES:
        raise StorageError(
            f"Direct upload capped at {MAX_DIRECT_UPLOAD_BYTES // (1024 * 1024)} MiB; use presigned upload"
        )

    # Enforce the storage quota before writing a single byte
    usage = UsageService(session)
    await usage.consume(tenant.organization_id, "storage_bytes", quantity=len(data))

    key = scoped_key(tenant.organization_id, upload.filename or "unnamed")
    await get_storage().put(
        key=key, data=data, content_type=upload.content_type or "application/octet-stream"
    )

    row = StoredFile(
        organization_id=tenant.organization_id,
        key=key,
        name=upload.filename or "unnamed",
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=len(data),
        created_by_user_id=user.id,
    )
    session.add(row)
    await session.flush()
    return FileRead.model_validate(row)


@router.get("/{file_id}")
async def download_file(file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> Response:
    await require_permission("file:read", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session)
    data = await get_storage().get(key=row.key)
    return Response(
        content=data,
        media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{row.name}"'},
    )


@router.post("/{file_id}/presign", response_model=PresignResponse)
async def presign_download(
    file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser
) -> PresignResponse:
    """Time-limited direct URL (S3 backends)."""
    await require_permission("file:read", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session)
    url = await get_storage().presign_get(key=row.key)
    from synapse_saas.core.config import get_settings

    return PresignResponse(url=url, key=row.key, expires_in=get_settings().storage_presign_seconds)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(file_id: UUID, tenant: TenantDep, session: SessionDep, user: CurrentUser) -> None:
    """Soft-delete the index row; quota accounting stops, bytes age out."""
    await require_permission("file:write", user, session, tenant)
    row = await _get_scoped(file_id, tenant.organization_id, session)
    from datetime import UTC, datetime

    row.deleted_at = datetime.now(UTC)
    await get_storage().delete(key=row.key)


async def _get_scoped(file_id: UUID, organization_id: UUID, session: SessionDep) -> StoredFile:
    from sqlalchemy import select

    row = (
        await session.execute(
            select(StoredFile).where(
                StoredFile.id == file_id,
                StoredFile.organization_id == organization_id,
                StoredFile.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("File not found")  # cross-tenant ⇒ same 404
    return row
