"""Unit tests for the domain-error → RFC 7807 mapping."""

from __future__ import annotations

from synapse_saas.core.errors import (
    DomainError,
    FeatureNotEntitledError,
    TenantNotResolvedError,
    UsageLimitExceededError,
)


class TestProblemDocument:
    def test_base_fields(self) -> None:
        err = TenantNotResolvedError("org not found")
        doc = err.to_problem(instance="/v1/orgs/x/projects", request_id="req_1")
        assert doc["status"] == 404
        assert doc["title"] == "not found"
        assert doc["detail"] == "org not found"
        assert doc["instance"] == "/v1/orgs/x/projects"
        assert doc["request_id"] == "req_1"
        assert doc["type"] == "https://synapse-saas.dev/problems/not_found"

    def test_extras_merged(self) -> None:
        err = FeatureNotEntitledError(
            "advanced_reports is not available on free",
            extras={"feature": "advanced_reports", "current_plan": "free", "available_in": ["pro"]},
        )
        doc = err.to_problem()
        assert doc["feature"] == "advanced_reports"
        assert doc["available_in"] == ["pro"]
        assert doc["status"] == 403

    def test_usage_limit_problem(self) -> None:
        err = UsageLimitExceededError(
            "api_requests limit exceeded",
            extras={"metric": "api_requests", "limit": 100, "used": 101},
        )
        assert err.to_problem()["status"] == 402

    def test_title_derived_from_class(self) -> None:
        assert UsageLimitExceededError().title == "usage_limit_exceeded"
        assert UsageLimitExceededError().problem_type.endswith("/usage_limit_exceeded")

    def test_message_defaults_to_title(self) -> None:
        assert DomainError().message == "domain_error"

    def test_status_codes_are_sane(self) -> None:
        assert TenantNotResolvedError.status == 404
        assert FeatureNotEntitledError.status == 403
        assert UsageLimitExceededError.status == 402
