"""Notification unit tests — templates, suppression, SMTP send."""

from __future__ import annotations

import pytest

pytestmark = []


class TestSmtpNotifier:
    async def test_suppressed_without_smtp_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.notifications.smtp import SmtpNotifier

        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "")
        get_settings.cache_clear()
        # Must not raise — suppression is the configured no-op path
        await SmtpNotifier().send(to="a@example.com", subject="s", body="b")
        get_settings.cache_clear()

    async def test_send_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SMTP down → logged, never raised (dispatch must survive)."""
        from synapse_saas.core.config import get_settings
        from synapse_saas.notifications import smtp as smtp_module

        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "smtp.invalid.test")
        get_settings.cache_clear()

        async def failing_send(message: object, host: str, port: int) -> None:
            raise ConnectionError("relaying denied")

        monkeypatch.setattr(smtp_module, "_send_message", failing_send)
        await smtp_module.SmtpNotifier().send(to="a@example.com", subject="s", body="b")
        get_settings.cache_clear()

    async def test_message_sent_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import smtplib as smtplib_module

        from synapse_saas.core.config import get_settings
        from synapse_saas.notifications import smtp as smtp_module

        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("SYNAPSE_SMTP_FROM", "noreply@example.test")
        get_settings.cache_clear()

        sent: list[object] = []

        class FakeSMTP:
            def __init__(self, host: str, port: int, timeout: int = 10) -> None:
                sent.append((host, port))

            def __enter__(self) -> FakeSMTP:
                return self

            def __exit__(self, *exc: object) -> None:
                pass

            def send_message(self, message: object) -> None:
                sent.append(message)

        monkeypatch.setattr(smtplib_module, "SMTP", FakeSMTP)
        await smtp_module.SmtpNotifier().send(to="user@example.com", subject="Hello", body="Body text")
        assert len(sent) == 2  # (host, port) + the message
        message = sent[1]
        assert message["To"] == "user@example.com"
        assert message["Subject"] == "Hello"
        get_settings.cache_clear()


class TestEventHandlers:
    async def test_invite_email_composed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.notifications import handlers

        captured: dict[str, str] = {}

        async def fake_send(*, to: str, subject: str, body: str) -> None:
            captured.update(to=to, subject=subject, body=body)

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))
        await handlers.handle_event(
            "member.invited",
            {"email": "new@example.com", "invite_token": "tok123", "org_name": "Acme"},
        )
        assert captured["to"] == "new@example.com"
        assert "Acme" in captured["subject"]
        assert "tok123" in captured["body"]

    async def test_reset_email_composed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.notifications import handlers

        captured: dict[str, str] = {}

        async def fake_send(*, to: str, subject: str, body: str) -> None:
            captured.update(to=to, subject=subject, body=body)

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))
        await handlers.handle_event("user.password_reset_link", {"email": "u@example.com", "token": "rtok"})
        assert "Reset" in captured["subject"]
        assert "rtok" in captured["body"]

    async def test_unknown_event_is_noop(self) -> None:
        from synapse_saas.notifications.handlers import handle_event

        await handle_event("something.else", {"x": 1})  # must not raise

    async def test_missing_fields_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.notifications import handlers

        called = []

        async def fake_send(*, to: str, subject: str, body: str) -> None:
            called.append(to)

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))
        await handlers.handle_event("member.invited", {"email": "x@example.com"})  # no token
        assert called == []
