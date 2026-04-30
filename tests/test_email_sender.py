# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for ``engramia.email.sender.send_email``.

The sender is patched out everywhere it's called, so its own SMTP branching
(STARTTLS on 587, implicit TLS on 465, plaintext on 25) was never tested
directly. This file covers each branch by patching ``smtplib.SMTP`` and
``smtplib.SMTP_SSL`` and asserting the call sequence.
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from engramia.email.sender import EmailNotConfigured, send_email


@pytest.fixture
def smtp_env(monkeypatch):
    monkeypatch.setenv("ENGRAMIA_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("ENGRAMIA_SMTP_PORT", "587")
    monkeypatch.setenv("ENGRAMIA_SMTP_USER", "noreply@example.com")
    monkeypatch.setenv("ENGRAMIA_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("ENGRAMIA_SMTP_FROM", "noreply@example.com")
    monkeypatch.setenv("ENGRAMIA_SMTP_USE_TLS", "true")


def _make_smtp_mock():
    """Returns (class_mock, instance_mock) with the context-manager wired up."""
    cls_mock = MagicMock()
    inst = MagicMock()
    cls_mock.return_value.__enter__ = MagicMock(return_value=inst)
    cls_mock.return_value.__exit__ = MagicMock(return_value=False)
    return cls_mock, inst


# ---------------------------------------------------------------------------
# Configuration errors (no SMTP call attempted)
# ---------------------------------------------------------------------------


class TestConfigErrors:
    def test_missing_host_raises_email_not_configured(self, monkeypatch):
        monkeypatch.delenv("ENGRAMIA_SMTP_HOST", raising=False)
        with pytest.raises(EmailNotConfigured, match="ENGRAMIA_SMTP_HOST"):
            send_email(to="a@b.cz", subject="x", html="<p>x</p>", text="x")

    def test_blank_host_raises(self, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_SMTP_HOST", "   ")
        with pytest.raises(EmailNotConfigured):
            send_email(to="a@b.cz", subject="x", html="<p>x</p>", text="x")

    def test_missing_from_raises_even_when_host_set(self, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_SMTP_HOST", "smtp.example.com")
        monkeypatch.delenv("ENGRAMIA_SMTP_FROM", raising=False)
        with pytest.raises(EmailNotConfigured, match="ENGRAMIA_SMTP_FROM"):
            send_email(to="a@b.cz", subject="x", html="<p>x</p>", text="x")


# ---------------------------------------------------------------------------
# Port 587 — STARTTLS upgrade on plaintext
# ---------------------------------------------------------------------------


class TestStartTLS:
    def test_port_587_uses_smtp_with_starttls(self, smtp_env):
        cls, inst = _make_smtp_mock()
        with patch("smtplib.SMTP", cls), patch("smtplib.SMTP_SSL") as ssl_cls:
            send_email(
                to="user@example.com",
                subject="Hello",
                html="<p>Hi</p>",
                text="Hi",
            )

        # SMTP class invoked, SMTP_SSL not.
        cls.assert_called_once_with("smtp.example.com", 587, timeout=15)
        ssl_cls.assert_not_called()

        # The order matters: ehlo → starttls → ehlo → login → send.
        method_names = [c[0] for c in inst.method_calls]
        assert method_names.index("ehlo") < method_names.index("starttls")
        assert method_names.count("ehlo") >= 2  # before AND after STARTTLS
        assert method_names.index("starttls") < method_names.index("login")
        assert method_names.index("login") < method_names.index("send_message")

        # Login carried the right credentials.
        login_call = next(c for c in inst.method_calls if c[0] == "login")
        assert login_call.args == ("noreply@example.com", "secret")

    def test_use_tls_false_skips_starttls(self, smtp_env, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_SMTP_PORT", "25")
        monkeypatch.setenv("ENGRAMIA_SMTP_USE_TLS", "false")
        cls, inst = _make_smtp_mock()
        with patch("smtplib.SMTP", cls):
            send_email(to="a@b.cz", subject="s", html="<p>x</p>", text="x")

        cls.assert_called_once_with("smtp.example.com", 25, timeout=15)
        method_names = [c[0] for c in inst.method_calls]
        assert "starttls" not in method_names

    def test_no_user_means_no_login_call(self, smtp_env, monkeypatch):
        """Some self-hosted MTAs accept relay without auth — login is skipped."""
        monkeypatch.delenv("ENGRAMIA_SMTP_USER", raising=False)
        cls, inst = _make_smtp_mock()
        with patch("smtplib.SMTP", cls):
            send_email(to="a@b.cz", subject="s", html="<p>x</p>", text="x")

        method_names = [c[0] for c in inst.method_calls]
        assert "login" not in method_names
        assert "send_message" in method_names


# ---------------------------------------------------------------------------
# Port 465 — implicit TLS (SMTPS), no STARTTLS
# ---------------------------------------------------------------------------


class TestImplicitTLS:
    def test_port_465_uses_smtp_ssl(self, smtp_env, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_SMTP_PORT", "465")
        ssl_cls, inst = _make_smtp_mock()
        with patch("smtplib.SMTP_SSL", ssl_cls), patch("smtplib.SMTP") as plain_cls:
            send_email(to="a@b.cz", subject="s", html="<p>x</p>", text="x")

        # SMTP_SSL invoked with (host, port, context, timeout).
        ssl_cls.assert_called_once()
        args, kwargs = ssl_cls.call_args
        assert args[0] == "smtp.example.com"
        assert args[1] == 465
        assert "context" in kwargs
        assert kwargs["timeout"] == 15

        # Plain SMTP class never used on 465.
        plain_cls.assert_not_called()

        method_names = [c[0] for c in inst.method_calls]
        # No ehlo / starttls dance on implicit TLS.
        assert "starttls" not in method_names
        assert "login" in method_names
        assert "send_message" in method_names


# ---------------------------------------------------------------------------
# SMTP failures propagate
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_smtp_exception_propagates_to_caller(self, smtp_env):
        cls = MagicMock()
        cls.return_value.__enter__ = MagicMock(
            side_effect=smtplib.SMTPConnectError(421, "service not available")
        )
        with patch("smtplib.SMTP", cls):
            with pytest.raises(smtplib.SMTPException):
                send_email(to="a@b.cz", subject="s", html="<p>x</p>", text="x")

    def test_recipient_rejected_propagates(self, smtp_env):
        cls, inst = _make_smtp_mock()
        inst.send_message.side_effect = smtplib.SMTPRecipientsRefused(
            {"a@b.cz": (550, b"unknown user")}
        )
        with patch("smtplib.SMTP", cls):
            with pytest.raises(smtplib.SMTPRecipientsRefused):
                send_email(to="a@b.cz", subject="s", html="<p>x</p>", text="x")


# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------


class TestMessageEnvelope:
    def test_message_carries_text_and_html_alternatives(self, smtp_env):
        cls, inst = _make_smtp_mock()
        with patch("smtplib.SMTP", cls):
            send_email(
                to="user@example.com",
                subject="Welcome to Engramia",
                html="<h1>Hi</h1>",
                text="Hi",
            )

        # send_message was called with an EmailMessage — inspect headers.
        call = next(c for c in inst.method_calls if c[0] == "send_message")
        msg = call.args[0]
        assert msg["From"] == "noreply@example.com"
        assert msg["To"] == "user@example.com"
        assert msg["Subject"] == "Welcome to Engramia"
        # Multipart/alternative — text first, html second.
        body = msg.get_body(("plain",))
        assert body is not None
        assert body.get_content().strip() == "Hi"
        html_part = msg.get_body(("html",))
        assert html_part is not None
        assert "<h1>Hi</h1>" in html_part.get_content()

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("", False),
            ("   ", False),
        ],
    )
    def test_use_tls_truthy_parsing(self, smtp_env, monkeypatch, value, expected):
        monkeypatch.setenv("ENGRAMIA_SMTP_PORT", "587")
        monkeypatch.setenv("ENGRAMIA_SMTP_USE_TLS", value)
        cls, inst = _make_smtp_mock()
        with patch("smtplib.SMTP", cls):
            send_email(to="a@b.cz", subject="s", html="<p>x</p>", text="x")
        method_names = [c[0] for c in inst.method_calls]
        assert ("starttls" in method_names) is expected
