"""Feature flag unit tests — bucketing, rollout determinism."""

from __future__ import annotations

from synapse_saas.feature_flags.service import BUCKETS, bucket_of, in_rollout

pytestmark = []


class TestBucketing:
    def test_bucket_in_range(self) -> None:
        for i in range(200):
            assert 0 <= bucket_of("flag", f"user-{i}") < BUCKETS

    def test_deterministic(self) -> None:
        assert bucket_of("flag", "user-1") == bucket_of("flag", "user-1")

    def test_flag_key_changes_bucket(self) -> None:
        # Not guaranteed for any single pair, but across many users the two
        # flags must distribute differently somewhere.
        users = [f"u{i}" for i in range(50)]
        assert any(bucket_of("a", u) != bucket_of("b", u) for u in users)

    def test_identifier_changes_bucket(self) -> None:
        users = [f"u{i}" for i in range(50)]
        assert any(bucket_of("a", users[0]) != bucket_of("a", u) for u in users[1:])


class TestRollout:
    def test_zero_percent_off_for_everyone(self) -> None:
        assert not any(in_rollout("f", f"u{i}", 0) for i in range(100))

    def test_hundred_percent_on_for_everyone(self) -> None:
        assert all(in_rollout("f", f"u{i}", 100) for i in range(100))

    def test_monotonic(self) -> None:
        """Raising the percentage can only add users, never remove them."""
        for i in range(60):
            user = f"u{i}"
            for pct in range(0, 100, 10):
                if in_rollout("f", user, pct):
                    assert in_rollout("f", user, pct + 5)

    def test_approximate_distribution(self) -> None:
        """50% rollout lands within a sane band around half the population."""
        enabled = sum(in_rollout("f", f"u{i}", 50) for i in range(1000))
        assert 400 <= enabled <= 600

    def test_stable_membership(self) -> None:
        """The same user resolves the same way on every check — no flapping."""
        user = "u-42"
        results = {in_rollout("f", user, 50) for _ in range(10)}
        assert len(results) == 1
