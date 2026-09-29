"""Xendit amounts are decimal major units; the port findings (P7) caught the float path."""

from __future__ import annotations

import pytest

from synapse_saas.billing.providers.xendit_provider import minor_units
from synapse_saas.core.errors import BillingProviderError


@pytest.mark.parametrize(
    ("raw", "cents"),
    [
        ("0.29", 29),
        (0.29, 29),
        ("499.99", 49999),
        (499.99, 49999),
        ("500", 50000),
        (500, 50000),
        ("1.005", 101),
    ],
)
def test_major_units_become_exact_minor_units(raw: object, cents: int) -> None:
    assert minor_units(raw) == cents


def test_garbage_is_a_provider_error() -> None:
    with pytest.raises(BillingProviderError):
        minor_units("twelve")
