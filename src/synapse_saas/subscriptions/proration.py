"""Proration for mid-period plan changes — a pure function.

Time-based, second-granular. Two views of the same split:

- `prorate()` — in advance: the unused fraction of the period is credited at
  the old price and charged at the new one (`net_cents`).
- `arrears_adjustment_cents()` — in arrears, which is how the invoicing engine
  bills (plan line for the whole period at the price in effect when the
  invoice is drafted): the elapsed fraction at the price difference.

No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True, slots=True)
class Proration:
    credit_cents: int  # unused portion of the old plan, refunded
    charge_cents: int  # same portion at the new price
    fraction_remaining: Decimal  # 0..1 of the period left at `now`

    @property
    def net_cents(self) -> int:
        """In-advance view: positive ⇒ the org owes this much now; negative ⇒ it is owed."""
        return self.charge_cents - self.credit_cents

    @property
    def elapsed_fraction(self) -> Decimal:
        return Decimal(1) - self.fraction_remaining


def arrears_adjustment_cents(
    old_cents: int,
    new_cents: int,
    period_start: datetime,
    period_end: datetime,
    now: datetime,
) -> int:
    """Correction line for a period invoiced IN ARREARS at the new price.

    The period invoice charges the new plan for the whole period; the org was
    on the old plan for the elapsed fraction. This returns that fraction at the
    price difference: negative (credit) on an upgrade, positive on a downgrade,
    so that `new_price + adjustment == old*elapsed + new*remaining`.
    """
    result = prorate(old_cents, new_cents, period_start, period_end, now)
    return _cents(old_cents - new_cents, result.elapsed_fraction)


def prorate(
    old_cents: int,
    new_cents: int,
    period_start: datetime,
    period_end: datetime,
    now: datetime,
) -> Proration:
    """Prorate a plan change at `now` inside [period_start, period_end).

    Clamped: before the period starts ⇒ the whole period; after it ends ⇒ nothing.
    A zero-length period prorates nothing (the renewal charges in full).
    """
    total = (period_end - period_start).total_seconds()
    if total <= 0:
        return Proration(credit_cents=0, charge_cents=0, fraction_remaining=Decimal(0))
    remaining = min(max((period_end - now).total_seconds(), 0.0), total)
    fraction = (Decimal(str(remaining)) / Decimal(str(total))).quantize(Decimal("0.000001"))
    return Proration(
        credit_cents=_cents(old_cents, fraction),
        charge_cents=_cents(new_cents, fraction),
        fraction_remaining=fraction,
    )


def _cents(amount: int, fraction: Decimal) -> int:
    return int((Decimal(amount) * fraction).quantize(Decimal(1), rounding=ROUND_HALF_UP))
