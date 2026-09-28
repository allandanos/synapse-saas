"""Problem documents (RFC 7807) are the one error shape of contract v1."""

from __future__ import annotations

from synapse_saas.core.errors import ConflictError, DomainError


def test_members_and_request_id_present() -> None:
    doc = ConflictError("taken", extras={"key": "x"}).to_problem(instance="/v1/things", request_id="req_1")
    assert doc == {
        "type": "https://synapse-saas.dev/problems/conflict",
        "title": "conflict",
        "status": 409,
        "detail": "taken",
        "instance": "/v1/things",
        "request_id": "req_1",
        "key": "x",
    }


def test_extras_never_shadow_the_standard_members() -> None:
    err = DomainError("x", extras={"status": "suspended", "title": "nope", "type": "evil", "detail": "d"})
    doc = err.to_problem(request_id="req_2")
    assert doc["status"] == 400 and doc["title"] == "domain error" and doc["detail"] == "x"
    assert doc["type"].startswith("https://synapse-saas.dev/problems/") and doc["request_id"] == "req_2"
