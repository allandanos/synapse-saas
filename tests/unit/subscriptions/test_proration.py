"""Proration is a pure function; these pin the arithmetic the invoices depend on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from synapse_saas.subscriptions.proration import arrears_adjustment_cents, prorate

START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(days=30)


class TestProrate:
    def test_halfway_splits_both_prices_in_half(self) -> None:
        result = prorate(10000, 30000, START, END, START + timedelta(days=15))
        assert result.fraction_remaining == Decimal("0.5")
        assert result.credit_cents == 5000
        assert result.charge_cents == 15000
        assert result.net_cents == 10000

    def test_before_the_period_starts_is_the_whole_period(self) -> None:
        result = prorate(10000, 30000, START, END, START - timedelta(days=3))
        assert result.fraction_remaining == Decimal(1)
        assert result.net_cents == 20000

    def test_after_the_period_ends_is_nothing(self) -> None:
        result = prorate(10000, 30000, START, END, END + timedelta(seconds=1))
        assert result.fraction_remaining == Decimal(0)
        assert (result.credit_cents, result.charge_cents, result.net_cents) == (0, 0, 0)

    def test_zero_length_period_prorates_nothing(self) -> None:
        result = prorate(10000, 30000, START, START, START)
        assert result.net_cents == 0

    def test_rounds_half_up_to_whole_cents(self) -> None:
        # 1/3 of the period left: 1000 * 0.333333 = 333.333 → 333; 5 * 0.333333 → 1.67 → 2
        now = START + timedelta(days=20)
        result = prorate(1000, 5, START, END, now)
        assert result.credit_cents == 333
        assert result.charge_cents == 2

    def test_downgrade_nets_a_credit(self) -> None:
        result = prorate(30000, 10000, START, END, START + timedelta(days=15))
        assert result.net_cents == -10000


class TestArrearsAdjustment:
    """The period invoice bills the NEW price for the whole period; the
    adjustment returns the elapsed fraction at the price difference so the
    total equals old*elapsed + new*remaining."""

    def test_upgrade_credits_the_elapsed_fraction(self) -> None:
        now = START + timedelta(days=15)
        adjustment = arrears_adjustment_cents(49900, 199900, START, END, now)
        assert adjustment == -75000
        assert 199900 + adjustment == 49900 * 0.5 + 199900 * 0.5

    def test_downgrade_charges_the_elapsed_fraction(self) -> None:
        now = START + timedelta(days=15)
        adjustment = arrears_adjustment_cents(199900, 49900, START, END, now)
        assert adjustment == 75000
        assert 49900 + adjustment == 199900 * 0.5 + 49900 * 0.5

    def test_change_at_period_start_needs_no_correction(self) -> None:
        assert arrears_adjustment_cents(49900, 199900, START, END, START) == 0

    def test_change_at_period_end_is_fully_the_old_price(self) -> None:
        assert arrears_adjustment_cents(49900, 199900, START, END, END) == -150000

    def test_same_price_is_zero(self) -> None:
        assert arrears_adjustment_cents(49900, 49900, START, END, START + timedelta(days=9)) == 0
