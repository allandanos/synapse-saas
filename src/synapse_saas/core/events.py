"""Canonical event-type constants.

Single vocabulary for audit_logs.event_type and outbox_events.event_type so producers
and consumers (webhook deliveries, notifications) never drift apart.
"""

from __future__ import annotations

# ── Identity ───────────────────────────────────────────────────────────────────
USER_REGISTERED = "user.registered"
USER_LOGIN_SUCCEEDED = "user.login_succeeded"
USER_LOGIN_FAILED = "user.login_failed"
USER_TOKEN_REFRESHED = "user.token_refreshed"
USER_TOKEN_REUSE_DETECTED = "user.token_reuse_detected"
USER_LOGGED_OUT = "user.logged_out"
USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
USER_PASSWORD_RESET_COMPLETED = "user.password_reset_completed"

# ── Tenancy ────────────────────────────────────────────────────────────────────
ORG_CREATED = "org.created"
ORG_UPDATED = "org.updated"
ORG_SUSPENDED = "org.suspended"
ORG_UNSUSPENDED = "org.unsuspended"
MEMBER_INVITED = "member.invited"
MEMBER_JOINED = "member.joined"
MEMBER_UPDATED = "member.updated"
MEMBER_REMOVED = "member.removed"
ROLE_CREATED = "role.created"
ROLE_UPDATED = "role.updated"
ROLE_DELETED = "role.deleted"
MEMBER_ROLE_ASSIGNED = "member.role_assigned"
MEMBER_ROLE_REVOKED = "member.role_revoked"

# ── Subscriptions / entitlements / billing ─────────────────────────────────────
SUBSCRIPTION_TRIAL_STARTED = "subscription.trial_started"
SUBSCRIPTION_ACTIVATED = "subscription.activated"
SUBSCRIPTION_UPDATED = "subscription.updated"
SUBSCRIPTION_PLAN_CHANGED = "subscription.plan_changed"
SUBSCRIPTION_CANCELED = "subscription.canceled"
SUBSCRIPTION_RESUMED = "subscription.resumed"
SUBSCRIPTION_PAST_DUE = "subscription.past_due"
SUBSCRIPTION_EXPIRED = "subscription.expired"
ENTITLEMENT_GRANTED = "entitlement.granted"
ENTITLEMENT_REVOKED = "entitlement.revoked"
ENTITLEMENT_EXPIRED = "entitlement.expired"
INVOICE_CREATED = "invoice.created"
INVOICE_PAID = "invoice.paid"
INVOICE_FAILED = "invoice.failed"

# ── Usage ──────────────────────────────────────────────────────────────────────
USAGE_SOFT_LIMIT_REACHED = "usage.soft_limit_reached"
USAGE_HARD_LIMIT_REACHED = "usage.hard_limit_reached"

# ── API keys ──────────────────────────────────────────────────────────────────
API_KEY_CREATED = "api_key.created"
API_KEY_REVOKED = "api_key.revoked"
API_KEY_AUTHENTICATED = "api_key.authenticated"

# ── Webhooks ───────────────────────────────────────────────────────────────────
WEBHOOK_ENDPOINT_CREATED = "webhook.endpoint_created"
WEBHOOK_ENDPOINT_UPDATED = "webhook.endpoint_updated"
WEBHOOK_ENDPOINT_DELETED = "webhook.endpoint_deleted"
WEBHOOK_DELIVERED = "webhook.delivered"
WEBHOOK_DELIVERY_FAILED = "webhook.delivery_failed"
WEBHOOK_DELIVERY_EXHAUSTED = "webhook.delivery_exhausted"
