"""Dev-seed unit tests: the loginable-email guard (no DB needed)."""

from __future__ import annotations

import pytest

from synapse_saas.seeds.dev_seed import DEV_ROLE_USERS, _assert_loginable_emails


class TestLoginableEmails:
    def test_every_role_email_passes_api_validation(self) -> None:
        # Would raise pydantic ValidationError on any reserved/invalid domain
        _assert_loginable_emails()

    def test_one_user_per_system_role(self) -> None:
        roles = [role for _, role in DEV_ROLE_USERS]
        assert sorted(roles) == ["admin", "billing", "developer", "member", "owner"]

    def test_guard_rejects_reserved_domain(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            # .test is special-use per RFC 6761 — EmailStr refuses it, which
            # is exactly the @acme.test bug this guard exists to prevent.
            import synapse_saas.seeds.dev_seed as ds

            original = ds.DEV_ROLE_USERS
            ds.DEV_ROLE_USERS = (("owner@acme.test", "owner"),)
            try:
                ds._assert_loginable_emails()
            finally:
                ds.DEV_ROLE_USERS = original
