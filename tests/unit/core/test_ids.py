"""Unit tests for ID and slug utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from synapse_saas.core.ids import (
    RESERVED_SLUGS,
    is_valid_slug,
    slugify,
    unique_slug,
    uuid_v7,
    uuid_v7_timestamp,
)


class TestUuidV7:
    def test_version_and_variant_bits(self) -> None:
        u = uuid_v7()
        assert u.version == 7
        assert (u.int >> 62) & 0b11 == 0b10

    def test_monotonically_recent_timestamp(self) -> None:
        before = datetime.now(UTC)
        u = uuid_v7()
        after = datetime.now(UTC)
        ts = uuid_v7_timestamp(u)
        assert before - timedelta(seconds=1) <= ts <= after + timedelta(seconds=1)

    def test_unique(self) -> None:
        assert len({str(uuid_v7()) for _ in range(1000)}) == 1000

    def test_roughly_time_ordered(self) -> None:
        # UUIDv7's whole point: lexicographic order follows creation order
        ids = sorted(str(uuid_v7()) for _ in range(50))
        assert ids == sorted(ids)


class TestSlugify:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Acme Corporation", "acme-corporation"),
            ("  Hello   World  ", "hello-world"),
            ("Foo__Bar--Baz!!!", "foo-bar-baz"),
            ("Ünïcödé Café", "n-c-d-caf"),  # non-ascii collapsed to separators
            ("", ""),
        ],
    )
    def test_slugify(self, raw: str, expected: str) -> None:
        assert slugify(raw) == expected

    def test_max_length(self) -> None:
        assert len(slugify("a" * 200)) <= 48

    def test_valid_slugs(self) -> None:
        assert is_valid_slug("acme")
        assert is_valid_slug("acme-corp-2")
        assert is_valid_slug("a" * 48)

    def test_invalid_slugs(self) -> None:
        assert not is_valid_slug("")  # empty
        assert not is_valid_slug("-acme")  # leading dash
        assert not is_valid_slug("acme-")  # trailing dash
        assert not is_valid_slug("Acme")  # uppercase
        assert not is_valid_slug("a" * 49)  # too long
        assert not is_valid_slug("under_score")  # underscore not allowed

    def test_reserved(self) -> None:
        assert RESERVED_SLUGS
        for slug in ("api", "www", "admin", "billing"):
            assert not is_valid_slug(slug)

    def test_unique_slug_has_suffix(self) -> None:
        s = unique_slug("Acme Corp")
        assert s.startswith("acme-corp-")
        assert is_valid_slug(s)
