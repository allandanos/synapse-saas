"""Notification unit tests — templates, suppression, SMTP send."""

from __future__ import annotations

from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path

import pytest

from synapse_saas.core.config import get_settings

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
        # The token rides the INTERNAL event; the public member.invited carries none
        await handlers.handle_event(
            "member.invite_email",
            {"email": "new@example.com", "invite_token": "tok123", "org_name": "Acme"},
        )
        assert captured["to"] == "new@example.com"
        assert "Acme" in captured["subject"]
        assert "tok123" in captured["body"]

    async def test_public_invite_event_sends_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.notifications import handlers

        sent: list[str] = []

        async def fake_send(*, to: str, subject: str, body: str, attachments: object = None) -> None:
            sent.append(to)

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))
        await handlers.handle_event("member.invited", {"email": "new@example.com", "org_name": "Acme"})
        assert sent == []

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


# ── P3 / D7: transport security, AUTH, and the notifier seam ─────────────────


class _FakeSMTP:
    """Records the protocol steps a real relay would see."""

    instances: list[_FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: int = 10, context: object = None) -> None:
        self.host, self.port, self.steps = host, port, ["connect"]
        self.ssl_context = context
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.steps.append("quit")

    def ehlo(self) -> None:
        self.steps.append("ehlo")

    def starttls(self, context: object = None) -> None:
        self.steps.append("starttls")
        self.ssl_context = context

    def login(self, username: str, password: str) -> None:
        self.steps.append(f"login:{username}")

    def send_message(self, message: object) -> None:
        self.steps.append("send")


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSMTP]:
    import smtplib

    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    return _FakeSMTP


class TestTransportSecurity:
    async def test_starttls_then_auth(self, fake_smtp: type[_FakeSMTP]) -> None:
        from email.message import EmailMessage

        from synapse_saas.notifications.smtp import _send_message

        await _send_message(
            EmailMessage(), "smtp.example.test", 587, tls="starttls", username="u", password="p"
        )
        (conn,) = fake_smtp.instances
        assert conn.steps == ["connect", "ehlo", "starttls", "ehlo", "login:u", "send", "quit"]
        assert conn.ssl_context is not None

    async def test_implicit_ssl(self, fake_smtp: type[_FakeSMTP]) -> None:
        from email.message import EmailMessage

        from synapse_saas.notifications.smtp import _send_message

        await _send_message(EmailMessage(), "smtp.example.test", 465, tls="ssl", username="u", password="p")
        (conn,) = fake_smtp.instances
        assert conn.ssl_context is not None and "starttls" not in conn.steps
        assert conn.steps == ["connect", "login:u", "send", "quit"]

    async def test_auth_over_plaintext_is_refused(self, fake_smtp: type[_FakeSMTP]) -> None:
        """Credentials never go over the wire in the clear."""
        from email.message import EmailMessage

        from synapse_saas.notifications.smtp import _send_message

        with pytest.raises(RuntimeError, match="plaintext"):
            await _send_message(
                EmailMessage(), "smtp.example.test", 25, tls="none", username="u", password="p"
            )
        assert "send" not in fake_smtp.instances[0].steps

    async def test_plaintext_without_auth_is_allowed_for_mailhog(self, fake_smtp: type[_FakeSMTP]) -> None:
        from email.message import EmailMessage

        from synapse_saas.notifications.smtp import _send_message

        await _send_message(EmailMessage(), "localhost", 1025)
        assert fake_smtp.instances[0].steps == ["connect", "send", "quit"]


class TestNotifierSeam:
    async def test_noop_when_no_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.notifications import NoopNotifier, get_notifier

        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "")
        get_settings.cache_clear()
        assert isinstance(get_notifier(), NoopNotifier)
        get_settings.cache_clear()

    async def test_noop_can_be_forced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.notifications import NoopNotifier, get_notifier

        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("SYNAPSE_NOTIFIER", "noop")
        get_settings.cache_clear()
        assert isinstance(get_notifier(), NoopNotifier)
        get_settings.cache_clear()

    async def test_smtp_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from synapse_saas.core.config import get_settings
        from synapse_saas.notifications import SmtpNotifier, get_notifier

        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("SYNAPSE_NOTIFIER", "smtp")
        get_settings.cache_clear()
        assert isinstance(get_notifier(), SmtpNotifier)
        get_settings.cache_clear()

    async def test_protocol_carries_attachments(self) -> None:
        from synapse_saas.notifications import Attachment, NoopNotifier

        await NoopNotifier().send(
            to="a@example.com",
            subject="s",
            body="b",
            attachments=[Attachment("x.pdf", b"%PDF-", "application/pdf")],
        )


# ── Branding: sender display name, product name, footer ──────────────────────


class TestBrandedEmail:
    def test_from_carries_the_brand_name(self, custom_branding: Callable[..., Path]) -> None:
        from synapse_saas.notifications.smtp import sender

        custom_branding(name="Acme Widgets")
        assert sender("noreply@acme.example.com") == "Acme Widgets <noreply@acme.example.com>"

    def test_from_name_beats_the_configured_display_name(self, custom_branding: Callable[..., Path]) -> None:
        from synapse_saas.notifications.smtp import sender

        custom_branding(email={"from_name": "Acme Billing"})
        assert sender("Ops <ops@acme.example.com>") == "Acme Billing <ops@acme.example.com>"

    def test_configured_display_name_beats_the_brand_name(self, custom_branding: Callable[..., Path]) -> None:
        from synapse_saas.notifications.smtp import sender

        custom_branding(name="Acme")
        assert sender("Ops Team <ops@acme.example.com>") == "Ops Team <ops@acme.example.com>"

    async def test_sent_message_has_the_display_name(
        self, monkeypatch: pytest.MonkeyPatch, custom_branding: Callable[..., Path]
    ) -> None:
        from synapse_saas.notifications import smtp as smtp_module

        custom_branding(name="Acme Widgets")
        monkeypatch.setenv("SYNAPSE_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("SYNAPSE_SMTP_FROM", "noreply@example.test")
        get_settings.cache_clear()
        captured: list[EmailMessage] = []

        async def fake_send(message: EmailMessage, *args: object, **kwargs: object) -> None:
            captured.append(message)

        monkeypatch.setattr(smtp_module, "_send_message", fake_send)
        await smtp_module.SmtpNotifier().send(to="u@example.com", subject="s", body="b")
        get_settings.cache_clear()
        assert captured[0]["From"] == "Acme Widgets <noreply@example.test>"

    async def test_every_email_names_the_product_and_ends_with_the_footer(
        self, monkeypatch: pytest.MonkeyPatch, custom_branding: Callable[..., Path]
    ) -> None:
        from synapse_saas.notifications import handlers

        custom_branding(name="Acme Widgets", links={"website": "https://acme.example.com"})
        sent: list[dict[str, str]] = []

        async def fake_send(*, to: str, subject: str, body: str, attachments: object = None) -> None:
            sent.append({"subject": subject, "body": body})

        async def fake_recipient(organization_id: str) -> str:
            return "billing@example.com"

        monkeypatch.setattr(handlers, "get_notifier", lambda: type("N", (), {"send": fake_send}))
        monkeypatch.setattr(handlers, "billing_recipient", fake_recipient)
        await handlers.handle_event(
            "member.invite_email", {"email": "a@example.com", "invite_token": "t", "org_name": "Org"}
        )
        await handlers.handle_event("user.password_reset_link", {"email": "a@example.com", "token": "t"})
        await handlers.handle_event(
            "usage.soft_limit_reached",
            {"organization_id": "o", "metric": "api_calls", "total": 80, "limit": 100},
        )
        for paid in (False, True):
            subject, body = handlers.invoice_message("INV-1", "499.00 PHP", paid=paid)
            sent.append({"subject": subject, "body": body})

        assert len(sent) == 5
        for email in sent:
            assert "Acme Widgets" in email["body"], email
            assert email["body"].endswith("\n\n— Acme Widgets\nhttps://acme.example.com"), email

    async def test_custom_footer_replaces_the_default(
        self, monkeypatch: pytest.MonkeyPatch, custom_branding: Callable[..., Path]
    ) -> None:
        from synapse_saas.notifications import handlers

        custom_branding(email={"footer": "Acme Widgets Inc. · 1 Example Street\n"})
        _subject, body = handlers.invoice_message("INV-1", "1.00 PHP", paid=False)
        assert body.endswith("\n\nAcme Widgets Inc. · 1 Example Street")
        assert "— " not in body
