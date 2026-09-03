"""Domain error hierarchy and RFC 7807 mapping.

Every service-raised error derives from `DomainError` and carries:
- `status`  — HTTP status the api layer maps it to
- `title`   — short, stable machine-readable problem title
- `extras`  — domain fields (feature, metric, limit…) merged into the problem document

Transport code never invents error semantics; services never build HTTP responses.
"""

from __future__ import annotations

from typing import Any

BASE_PROBLEM_URI = "https://synapse-saas.dev/problems"


class DomainError(Exception):
    """Base for all framework domain errors."""

    status: int = 400
    title: str = "domain_error"

    def __init__(self, message: str = "", *, extras: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.title)
        self.message = message or self.title
        self.extras: dict[str, Any] = dict(extras or {})

    @property
    def problem_type(self) -> str:
        return f"{BASE_PROBLEM_URI}/{self.title}"

    def to_problem(self, *, instance: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "type": self.problem_type,
            "title": self.title.replace("_", " "),
            "status": self.status,
            "detail": self.message,
        }
        if instance is not None:
            doc["instance"] = instance
        if request_id is not None:
            doc["request_id"] = request_id
        doc.update(self.extras)
        return doc


# ── Core / context ─────────────────────────────────────────────────────────────


class TenantContextMissingError(DomainError):
    status = 400
    title = "tenant_context_missing"


class TenantViolationError(DomainError):
    """A write attempted to attach an object to a different tenant than the active context."""

    status = 403
    title = "tenant_violation"


class TenantNotResolvedError(DomainError):
    """Org could not be resolved OR the user is not a member. Deliberately 404 — never leak existence."""

    status = 404
    title = "not_found"


# ── Identity ───────────────────────────────────────────────────────────────────


class AuthenticationError(DomainError):
    status = 401
    title = "unauthorized"


class InvalidCredentialsError(AuthenticationError):
    title = "invalid_credentials"


class TokenReuseError(AuthenticationError):
    """A rotated refresh token was replayed — possible theft. Chain is revoked."""

    title = "token_reuse_detected"


class EmailAlreadyRegisteredError(DomainError):
    status = 409
    title = "email_already_registered"


class WeakPasswordError(DomainError):
    title = "weak_password"


class UserNotFoundError(DomainError):
    status = 404
    title = "user_not_found"


# ── Tenancy ────────────────────────────────────────────────────────────────────


class OrganizationNotFoundError(DomainError):
    status = 404
    title = "not_found"


class SlugUnavailableError(DomainError):
    status = 409
    title = "slug_unavailable"


class MembershipLimitReachedError(DomainError):
    status = 402
    title = "usage_limit_exceeded"


class NotAMemberError(DomainError):
    status = 404
    title = "not_found"


class InviteNotFoundError(DomainError):
    status = 404
    title = "invite_not_found"


class InviteAlreadyUsedError(DomainError):
    status = 409
    title = "invite_already_used"


# ── Authorization ──────────────────────────────────────────────────────────────


class PermissionDeniedError(DomainError):
    status = 403
    title = "permission_denied"


class RoleNotFoundError(DomainError):
    status = 404
    title = "role_not_found"


class SystemRoleImmutableError(DomainError):
    status = 409
    title = "system_role_immutable"


# ── Plans / subscriptions ──────────────────────────────────────────────────────


class PlanNotFoundError(DomainError):
    status = 404
    title = "plan_not_found"


class PlanNotPublicError(DomainError):
    status = 404
    title = "plan_not_found"


class CatalogInvalidError(DomainError):
    title = "plan_catalog_invalid"


class SubscriptionNotFoundError(DomainError):
    status = 404
    title = "subscription_not_found"


class SubscriptionStateError(DomainError):
    status = 409
    title = "invalid_subscription_transition"


class TrialNotAllowedError(DomainError):
    status = 409
    title = "trial_not_allowed"


# ── Entitlements ───────────────────────────────────────────────────────────────


class FeatureNotEntitledError(DomainError):
    status = 403
    title = "feature_not_entitled"


class EntitlementNotFoundError(DomainError):
    status = 404
    title = "entitlement_not_found"


# ── Usage ──────────────────────────────────────────────────────────────────────


class UsageLimitExceededError(DomainError):
    status = 402
    title = "usage_limit_exceeded"


class UnknownMetricError(DomainError):
    status = 422
    title = "unknown_metric"


# ── Billing ────────────────────────────────────────────────────────────────────


class BillingProviderError(DomainError):
    status = 502
    title = "billing_provider_error"


class BillingProviderNotConfiguredError(DomainError):
    status = 409
    title = "billing_provider_not_configured"


class WebhookSignatureInvalidError(DomainError):
    status = 400
    title = "webhook_signature_invalid"


class InvoiceNotFoundError(DomainError):
    status = 404
    title = "invoice_not_found"


# ── Feature flags ─────────────────────────────────────────────────────────────


class FeatureFlagNotFoundError(DomainError):
    status = 404
    title = "feature_flag_not_found"


# ── Storage ───────────────────────────────────────────────────────────────────


class StorageError(DomainError):
    title = "storage_error"


# ── API keys ──────────────────────────────────────────────────────────────────


class ApiKeyNotFoundError(DomainError):
    status = 404
    title = "api_key_not_found"


# ── Webhooks (outbound) ────────────────────────────────────────────────────────


class WebhookEndpointNotFoundError(DomainError):
    status = 404
    title = "webhook_endpoint_not_found"


class WebhookDeliveryNotFoundError(DomainError):
    status = 404
    title = "webhook_delivery_not_found"


# ── Misc ───────────────────────────────────────────────────────────────────────


class ValidationFailedError(DomainError):
    status = 422
    title = "validation_failed"


class NotFoundError(DomainError):
    status = 404
    title = "not_found"


class ConflictError(DomainError):
    status = 409
    title = "conflict"


class RateLimitedError(DomainError):
    status = 429
    title = "rate_limited"
