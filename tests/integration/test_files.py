"""File storage end-to-end: upload, download, quota, feature gate, isolation."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.pg


@pytest.fixture(autouse=True)
async def _local_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Local-disk backend in a temp dir; reset around each test."""
    from synapse_saas.core.config import get_settings
    from synapse_saas.storage import backend as backend_module

    monkeypatch.setenv("SYNAPSE_S3_BUCKET", "")
    monkeypatch.setenv("SYNAPSE_STORAGE_ROOT", str(tmp_path / "store"))
    get_settings.cache_clear()
    backend_module.reset_storage()
    yield
    get_settings.cache_clear()
    backend_module.reset_storage()


def org_headers(fixture: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {fixture['access_token']}",
        "X-Org-Id": fixture["org_id"],
    }


def multipart(filename: str, content: bytes, content_type: str = "text/plain") -> dict:
    return {"files": ("file", content, content_type)} | {"_filename": filename}  # type: ignore[dict-item]


async def upload(client: AsyncClient, fixture: dict[str, str], name: str, content: bytes):
    return await client.post(
        "/v1/files",
        headers=org_headers(fixture),
        files={"file": (name, content, "text/plain")},
    )


class TestUploadDownload:
    async def test_upload_then_download(self, client: AsyncClient, org_and_tokens) -> None:
        res = await upload(client, org_and_tokens, "notes.txt", b"file content here")
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["name"] == "notes.txt"
        assert body["size_bytes"] == len(b"file content here")

        downloaded = await client.get(f"/v1/files/{body['id']}", headers=org_headers(org_and_tokens))
        assert downloaded.status_code == 200
        assert downloaded.content == b"file content here"
        assert downloaded.headers["content-type"].startswith("text/plain")

    async def test_list_scoped_to_org(self, client: AsyncClient, org_and_tokens) -> None:
        await upload(client, org_and_tokens, "a.txt", b"a")
        await upload(client, org_and_tokens, "b.txt", b"b")
        listed = (await client.get("/v1/files", headers=org_headers(org_and_tokens))).json()
        assert len(listed) == 2

    async def test_nested_path(self, client: AsyncClient, org_and_tokens) -> None:
        res = await upload(client, org_and_tokens, "reports/q1.txt", b"nested")
        assert res.status_code == 201
        assert res.json()["key"].endswith("reports/q1.txt")

    async def test_delete_then_404(self, client: AsyncClient, org_and_tokens) -> None:
        created = await upload(client, org_and_tokens, "gone.txt", b"x")
        file_id = created.json()["id"]

        gone = await client.delete(f"/v1/files/{file_id}", headers=org_headers(org_and_tokens))
        assert gone.status_code == 204
        after = await client.get(f"/v1/files/{file_id}", headers=org_headers(org_and_tokens))
        assert after.status_code == 404


class TestQuota:
    async def test_storage_metered(self, client: AsyncClient, org_and_tokens) -> None:
        payload = b"x" * 1234
        await upload(client, org_and_tokens, "metered.bin", payload)
        check = (
            await client.get(
                "/v1/usage/check",
                headers=org_headers(org_and_tokens),
                params={"metric": "storage_bytes"},
            )
        ).json()
        assert check["used"] >= 1234

    async def test_quota_breach_402(self, client: AsyncClient, org_and_tokens) -> None:
        """Free plan storage_bytes = 1 GiB — cap via a tight addon, then upload."""
        grant = await client.post(
            "/v1/entitlements/grants",
            headers=org_headers(org_and_tokens),
            json={
                "feature_key": "limit:storage_bytes",
                "source": "addon",
                "limit_value": 100,
            },
        )
        assert grant.status_code == 201

        ok = await upload(client, org_and_tokens, "small.txt", b"x" * 50)
        assert ok.status_code == 201

        blocked = await upload(client, org_and_tokens, "big.txt", b"x" * 200)
        assert blocked.status_code == 402
        problem = blocked.json()
        assert problem["metric"] == "storage_bytes"
        assert problem["limit"] == 100


class TestFeatureGate:
    async def test_upload_requires_api_access(self, client: AsyncClient, org_and_tokens) -> None:
        """Revoke api_access (kill switch) and uploads turn into 403 upgrade prompts."""
        from synapse_saas.core.cache import VersionedCache

        await client.post(
            "/v1/entitlements/grants",
            headers=org_headers(org_and_tokens),
            json={"feature_key": "api_access", "source": "override", "enabled": False},
        )
        await VersionedCache("entl").bump(org_and_tokens["org_id"])

        res = await upload(client, org_and_tokens, "blocked.txt", b"data")
        assert res.status_code == 403
        assert res.json().get("feature") == "api_access"
        assert "available_in" in res.json()


class TestIsolation:
    async def test_cross_org_download_404(self, client: AsyncClient, org_and_tokens) -> None:
        created = await upload(client, org_and_tokens, "secret.txt", b"tenant data")
        file_id = created.json()["id"]

        rival = await client.post(
            "/v1/auth/register",
            json={
                "email": "filerival@example.com",
                "password": "password12345",
                "display_name": "F",
            },
        )
        rival_token = rival.json()["tokens"]["access_token"]
        rival_org = (
            await client.post(
                "/v1/orgs",
                headers={"Authorization": f"Bearer {rival_token}"},
                json={"name": "Rival Files"},
            )
        ).json()["id"]

        foreign = await client.get(
            f"/v1/files/{file_id}",
            headers={"Authorization": f"Bearer {rival_token}", "X-Org-Id": rival_org},
        )
        phantom = await client.get(
            f"/v1/files/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {rival_token}", "X-Org-Id": rival_org},
        )
        assert foreign.status_code == phantom.status_code == 404
        foreign_body, phantom_body = foreign.json(), phantom.json()
        foreign_body.pop("instance"), phantom_body.pop("instance")
        assert foreign_body == phantom_body

    async def test_key_namespace_is_org_scoped(self, client: AsyncClient, org_and_tokens) -> None:
        """Keys are always {org_id}/… — the tenant boundary extends to bytes."""
        created = await upload(client, org_and_tokens, "scoped.txt", b"s")
        assert created.json()["key"].startswith(org_and_tokens["org_id"])
