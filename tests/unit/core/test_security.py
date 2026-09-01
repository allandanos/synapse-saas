"""Unit tests for security primitives: argon2, JWT, token hashing, signatures."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from synapse_saas.core import security
from synapse_saas.core.config import get_settings
from synapse_saas.core.errors import AuthenticationError
from synapse_saas.core.security import (
    constant_time_equals,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    sign_payload,
    verify_password,
    verify_signature,
)


class TestPasswords:
    def test_hash_and_verify(self) -> None:
        h = hash_password("correct horse battery staple")
        assert h != "correct horse battery staple"
        assert verify_password("correct horse battery staple", h)

    def test_wrong_password(self) -> None:
        h = hash_password("right")
        assert not verify_password("wrong", h)

    def test_malformed_hash_rejected(self) -> None:
        assert not verify_password("x", "not-an-argon2-hash")

    def test_hash_is_salted(self) -> None:
        assert hash_password("same") != hash_password("same")


class TestAccessToken:
    def test_round_trip(self) -> None:
        user_id = uuid4()
        org_id = uuid4()
        token = create_access_token(user_id, email="u@example.com", organization_id=org_id)
        payload = decode_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["org"] == str(org_id)
        assert payload["email"] == "u@example.com"
        assert payload["type"] == "access"

    def test_platform_admin_claim(self) -> None:
        token = create_access_token(uuid4(), email="a@b.c", is_platform_admin=True)
        assert decode_access_token(token)["platform_admin"] is True

    def test_expired_token_rejected(self) -> None:
        token = create_access_token(uuid4(), email="u@example.com", ttl_seconds=-10)
        with pytest.raises(AuthenticationError):
            decode_access_token(token)

    def test_wrong_secret_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        token = create_access_token(uuid4(), email="u@example.com")
        tampered = get_settings().model_copy(update={"secret_key": "attacker-secret-attacker-secret-32b!"})
        monkeypatch.setattr(security, "get_settings", lambda: tampered)
        with pytest.raises(AuthenticationError):
            decode_access_token(token)
        monkeypatch.undo()

    def test_alg_none_forgery_rejected(self) -> None:
        import jwt

        forged = jwt.encode({"sub": "x", "type": "access"}, key=None, algorithm="none")
        with pytest.raises(AuthenticationError):
            decode_access_token(forged)

    def test_refresh_token_type_rejected_as_access(self) -> None:
        # A token signed with our key but wrong type must not authenticate
        import jwt

        from synapse_saas.core.config import get_settings

        wrong_type = jwt.encode(
            {"sub": str(uuid4()), "type": "refresh", "exp": int(time.time()) + 60, "iat": int(time.time())},
            get_settings().secret_key,
            algorithm="HS256",
        )
        with pytest.raises(AuthenticationError):
            decode_access_token(wrong_type)


class TestRefreshTokens:
    def test_format_and_uniqueness(self) -> None:
        tokens = {generate_refresh_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_hash_is_stable_and_not_reversible_output(self) -> None:
        t = generate_refresh_token()
        assert hash_refresh_token(t) == hash_refresh_token(t)
        assert hash_refresh_token(t) != t


class TestSignatures:
    def test_sign_and_verify(self) -> None:
        body = b'{"hello": "world"}'
        ts = int(time.time())
        sig = sign_payload(body, "whsec_test", timestamp=ts)
        assert verify_signature(body, "whsec_test", timestamp=ts, signature=sig)

    def test_tampered_body(self) -> None:
        ts = int(time.time())
        sig = sign_payload(b"original", "whsec_test", timestamp=ts)
        assert not verify_signature(b"tampered", "whsec_test", timestamp=ts, signature=sig)

    def test_wrong_secret(self) -> None:
        ts = int(time.time())
        sig = sign_payload(b"body", "right", timestamp=ts)
        assert not verify_signature(b"body", "wrong", timestamp=ts, signature=sig)

    def test_timestamp_in_signed_payload(self) -> None:
        # Changing ts changes signature — replay across times is detectable
        body = b"body"
        sig = sign_payload(body, "s", timestamp=1000)
        assert not verify_signature(body, "s", timestamp=2000, signature=sig)

    def test_constant_time_compare(self) -> None:
        assert constant_time_equals("abc", "abc")
        assert not constant_time_equals("abc", "abd")
