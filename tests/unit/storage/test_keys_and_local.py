"""Storage unit tests — key validation, org scoping, local backend."""

from __future__ import annotations

from uuid import uuid4

import pytest

from synapse_saas.core.errors import StorageError, TenantViolationError
from synapse_saas.storage.backend import LocalDiskStorage, scoped_key, validate_key

pytestmark = []


class TestKeyValidation:
    def test_valid_key(self) -> None:
        validate_key(f"{uuid4()}/reports/q1.pdf")

    def test_rejects_empty_and_garbage(self) -> None:
        with pytest.raises(StorageError):
            validate_key("")
        with pytest.raises(StorageError):
            validate_key("../etc/passwd")
        with pytest.raises(StorageError):
            validate_key("has space/file.txt")

    def test_org_prefix_enforced(self) -> None:
        org = uuid4()
        other = uuid4()
        with pytest.raises(TenantViolationError):
            validate_key(f"{other}/file.txt", organization_id=org)

    def test_scoped_key_builds_valid(self) -> None:
        org = uuid4()
        key = scoped_key(org, "reports/q1.pdf")
        assert key.startswith(str(org))
        validate_key(key, organization_id=org)  # must not raise

    def test_scoped_key_rejects_traversal(self) -> None:
        with pytest.raises(StorageError):
            scoped_key(uuid4(), "../../etc/passwd")


class TestLocalDiskBackend:
    async def test_round_trip(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.storage import backend as backend_module

        monkeypatch.setenv("SYNAPSE_S3_BUCKET", "")  # force local
        monkeypatch.setenv("SYNAPSE_STORAGE_ROOT", str(tmp_path / "store"))
        get_settings.cache_clear()
        backend_module.reset_storage()

        storage = backend_module.get_storage()
        assert isinstance(storage, LocalDiskStorage)

        org = uuid4()
        key = scoped_key(org, "docs/readme.txt")
        await storage.put(key=key, data=b"hello storage", content_type="text/plain")
        assert await storage.get(key=key) == b"hello storage"

        await storage.delete(key=key)
        from synapse_saas.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await storage.get(key=key)

        get_settings.cache_clear()
        backend_module.reset_storage()

    async def test_missing_file_404(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.core.errors import NotFoundError
        from synapse_saas.storage import backend as backend_module

        monkeypatch.setenv("SYNAPSE_S3_BUCKET", "")
        monkeypatch.setenv("SYNAPSE_STORAGE_ROOT", str(tmp_path))
        get_settings.cache_clear()
        backend_module.reset_storage()

        with pytest.raises(NotFoundError):
            await backend_module.get_storage().get(key=f"{uuid4()}/none.bin")
        get_settings.cache_clear()
        backend_module.reset_storage()

    async def test_presign_unsupported_on_local(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.storage import backend as backend_module

        monkeypatch.setenv("SYNAPSE_S3_BUCKET", "")
        monkeypatch.setenv("SYNAPSE_STORAGE_ROOT", str(tmp_path))
        get_settings.cache_clear()
        backend_module.reset_storage()

        with pytest.raises(StorageError, match="S3"):
            await backend_module.get_storage().presign_get(key=f"{uuid4()}/f")
        get_settings.cache_clear()
        backend_module.reset_storage()


class TestBackendSelection:
    def test_local_when_no_bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.storage import backend as backend_module

        monkeypatch.setenv("SYNAPSE_S3_BUCKET", "")
        get_settings.cache_clear()
        backend_module.reset_storage()
        assert isinstance(backend_module.get_storage(), LocalDiskStorage)
        get_settings.cache_clear()
        backend_module.reset_storage()

    def test_s3_when_bucket_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.storage import backend as backend_module

        monkeypatch.setenv("SYNAPSE_S3_BUCKET", "synapse-test")
        get_settings.cache_clear()
        backend_module.reset_storage()
        assert isinstance(backend_module.get_storage(), backend_module.S3Storage)
        get_settings.cache_clear()
        backend_module.reset_storage()
