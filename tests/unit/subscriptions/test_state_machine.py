"""Unit tests for the subscription state machine."""

from __future__ import annotations

import pytest

from synapse_saas.core.errors import SubscriptionStateError
from synapse_saas.subscriptions.state_machine import (
    OCCUPYING_STATUSES,
    assert_transition,
    can_transition,
)


class TestLegalTransitions:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            ("incomplete", "trialing"),
            ("incomplete", "active"),
            ("trialing", "active"),
            ("trialing", "canceled"),
            ("active", "past_due"),
            ("active", "canceled"),
            ("active", "unpaid"),
            ("past_due", "active"),  # payment recovered
            ("past_due", "canceled"),
            ("unpaid", "canceled"),
            ("canceled", "active"),  # resume
        ],
    )
    def test_legal(self, current: str, target: str) -> None:
        assert can_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            ("canceled", "trialing"),  # cannot re-trial a dead subscription
            ("canceled", "past_due"),
            ("unpaid", "trialing"),
            ("incomplete", "unpaid"),
        ],
    )
    def test_illegal(self, current: str, target: str) -> None:
        assert not can_transition(current, target)

    def test_same_state_is_idempotent(self) -> None:
        for status in ("trialing", "active", "past_due", "canceled"):
            assert can_transition(status, status)

    def test_assert_raises_with_context(self) -> None:
        with pytest.raises(SubscriptionStateError) as exc_info:
            assert_transition("canceled", "trialing")
        assert exc_info.value.extras["from"] == "canceled"
        assert "allowed" in exc_info.value.extras

    def test_assert_accepts_idempotent(self) -> None:
        assert_transition("active", "active")

    def test_occupying_statuses(self) -> None:
        assert {"trialing", "active", "past_due"} == OCCUPYING_STATUSES
