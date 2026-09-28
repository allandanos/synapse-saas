"""FgaClient over respx: request shapes, tolerance, and failure surfacing."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from synapse_saas.authorization.fga import FgaClient, FgaError, Tuple

URL = "http://fga.test"


def client() -> FgaClient:
    return FgaClient(url=URL, store_id="st", model_id="m1", api_token="tok", http=httpx.AsyncClient())


class TestCheck:
    @respx.mock
    async def test_check_sends_tuple_and_model(self) -> None:
        route = respx.post(f"{URL}/stores/st/check").mock(return_value=Response(200, json={"allowed": True}))
        assert await client().check("user:u1", "can_org_read", "organization:o1") is True
        body = route.calls.last.request.read().decode()
        assert '"user":"user:u1"' in body.replace(
            " ", ""
        ) and '"authorization_model_id":"m1"' in body.replace(" ", "")
        assert route.calls.last.request.headers["Authorization"] == "Bearer tok"

    @respx.mock
    async def test_denied(self) -> None:
        respx.post(f"{URL}/stores/st/check").mock(return_value=Response(200, json={"allowed": False}))
        assert await client().check("user:u1", "can_org_delete", "organization:o1") is False

    @respx.mock
    async def test_non_2xx_is_an_fga_error(self) -> None:
        respx.post(f"{URL}/stores/st/check").mock(return_value=Response(500, text="boom"))
        with pytest.raises(FgaError, match="500"):
            await client().check("user:u1", "can_org_read", "organization:o1")

    @respx.mock
    async def test_unreachable_is_an_fga_error(self) -> None:
        respx.post(f"{URL}/stores/st/check").mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(FgaError, match="unreachable"):
            await client().check("user:u1", "can_org_read", "organization:o1")

    async def test_unconfigured(self) -> None:
        with pytest.raises(FgaError, match="not configured"):
            await FgaClient(url="", store_id="", http=httpx.AsyncClient()).check("u", "r", "o")


class TestWrite:
    @respx.mock
    async def test_writes_and_deletes_one_tuple_per_request(self) -> None:
        route = respx.post(f"{URL}/stores/st/write").mock(return_value=Response(200, json={}))
        await client().write(
            writes=[
                Tuple("user:u1", "owner", "organization:o1"),
                Tuple("user:u1", "can_x", "organization:o1"),
            ],
            deletes=[Tuple("user:u1", "member", "organization:o1")],
        )
        assert route.call_count == 3
        bodies = [c.request.read().decode() for c in route.calls]
        assert '"writes"' in bodies[0] and '"deletes"' in bodies[2]

    @respx.mock
    async def test_duplicate_write_and_missing_delete_are_tolerated(self) -> None:
        respx.post(f"{URL}/stores/st/write").mock(
            side_effect=[
                Response(
                    400, json={"code": "write_failed_due_to_invalid_input", "message": "tuple already exists"}
                ),
                Response(
                    400, json={"code": "write_failed_due_to_invalid_input", "message": "tuple not found"}
                ),
            ]
        )
        await client().write(
            writes=[Tuple("user:u1", "owner", "organization:o1")],
            deletes=[Tuple("user:u1", "x", "organization:o1")],
        )


class TestStoresAndModels:
    @respx.mock
    async def test_create_store_and_write_model(self) -> None:
        respx.post(f"{URL}/stores").mock(return_value=Response(201, json={"id": "new-store"}))
        respx.post(f"{URL}/stores/new-store/authorization-models").mock(
            return_value=Response(201, json={"authorization_model_id": "model-1"})
        )
        c = FgaClient(url=URL, store_id="", http=httpx.AsyncClient())
        c.store_id = await c.create_store("synapse")
        assert c.store_id == "new-store"
        assert await c.write_model({"schema_version": "1.1", "type_definitions": []}) == "model-1"

    @respx.mock
    async def test_read_tuples(self) -> None:
        respx.post(f"{URL}/stores/st/read").mock(
            return_value=Response(
                200,
                json={
                    "tuples": [{"key": {"user": "user:u1", "relation": "owner", "object": "organization:o1"}}]
                },
            )
        )
        assert await client().read_tuples("organization:o1") == [Tuple("user:u1", "owner", "organization:o1")]
