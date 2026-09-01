"""Subscription status state machine.

Webhooks from providers can arrive out of order and be replayed; transitions
must be idempotent and monotonic. This table is the single definition of which
transitions are legal.
"""

from __future__ import annotations

from synapse_saas.core.errors import SubscriptionStateError

# status → set of statuses it may move to
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "incomplete": frozenset({"trialing", "active", "past_due", "canceled"}),
    "trialing": frozenset({"active", "past_due", "canceled", "incomplete"}),
    "active": frozenset({"past_due", "canceled", "unpaid", "active"}),  # active→active = plan change
    "past_due": frozenset({"active", "canceled", "unpaid"}),
    "unpaid": frozenset({"active", "canceled"}),
    "canceled": frozenset({"active"}),  # resume
}

# Statuses whose plan features are in effect (entitlement resolver uses this)
OCCUPYING_STATUSES = frozenset({"trialing", "active", "past_due"})


def can_transition(current: str, target: str) -> bool:
    if current == target:
        return True  # idempotent re-assertion (webhook replays)
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        allowed = sorted(ALLOWED_TRANSITIONS.get(current, frozenset()))
        raise SubscriptionStateError(
            f"Cannot transition subscription from {current!r} to {target!r}",
            extras={"from": current, "to": target, "allowed": allowed},
        )
