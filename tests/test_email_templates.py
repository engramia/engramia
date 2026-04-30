# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for ``engramia.email.templates``.

The templates use plain f-strings — no Jinja, no template engine. The only
sensitive surface is HTML escaping of caller-supplied values (recipient
name, verify URL). A future template change adding an unescaped variable
must fail loudly here so we don't ship XSS to users' inboxes.
"""

from __future__ import annotations

import pytest

from engramia.email.templates import (
    account_deletion_email,
    reminder_email,
    verification_email,
)


_XSS = '"><script>alert(1)</script>'
_XSS_NAME = '<img src=x onerror="alert(1)">'


# ---------------------------------------------------------------------------
# verification_email
# ---------------------------------------------------------------------------


class TestVerificationEmail:
    def test_returns_subject_text_html_triple(self):
        subject, text, html = verification_email(
            verify_url="https://app/verify?token=abc",
            recipient_name="Alice",
        )
        assert subject == "Verify your Engramia account"
        assert isinstance(text, str)
        assert isinstance(html, str)
        assert html.lstrip().startswith("<!doctype html>")

    def test_url_appears_in_text_unmodified(self):
        url = "https://app.engramia.dev/verify?token=ABC&utm=nope"
        _, text, _ = verification_email(verify_url=url, recipient_name=None)
        # Plain-text body must keep the URL exactly so most clients render it.
        assert url in text

    def test_url_html_escaped_in_href(self):
        url = 'https://app/verify?token=abc"><script>alert(1)</script>'
        _, _, html = verification_email(verify_url=url, recipient_name=None)
        # The raw payload must not appear in the HTML.
        assert "<script>alert(1)</script>" not in html
        # The HTML-escaped form is present inside the href quoting.
        assert "&lt;script&gt;" in html
        # Quote was escaped (avoids breaking out of the href attribute).
        assert "&quot;" in html

    def test_recipient_name_html_escaped(self):
        _, _, html = verification_email(
            verify_url="https://app/verify?token=t",
            recipient_name=_XSS_NAME,
        )
        assert '<img src=x onerror="alert(1)">' not in html
        assert "&lt;img" in html

    def test_no_name_uses_fallback_greeting(self):
        _, text, html = verification_email(
            verify_url="https://app/verify?token=t", recipient_name=None
        )
        assert text.startswith("Hi,\n\n")
        assert "<p>Hi,</p>" in html

    def test_named_recipient_uses_personal_greeting(self):
        _, text, html = verification_email(
            verify_url="https://app/verify?token=t", recipient_name="Bob"
        )
        assert text.startswith("Hi Bob,\n\n")
        assert "Hi Bob," in html

    def test_expires_hours_interpolated(self):
        _, text, html = verification_email(
            verify_url="https://app/verify?token=t",
            recipient_name=None,
            expires_hours=48,
        )
        assert "valid for 48 hours" in text
        assert "expires in 48 hours" in html


# ---------------------------------------------------------------------------
# account_deletion_email
# ---------------------------------------------------------------------------


class TestAccountDeletionEmail:
    def test_returns_triple(self):
        subject, text, html = account_deletion_email(
            confirm_url="https://app/confirm?token=del",
            recipient_name="Alice",
        )
        assert subject == "Confirm Engramia account deletion"
        assert "permanently delete" in text
        assert "permanently delete" in html.lower()

    def test_url_html_escaped_in_href(self):
        _, _, html = account_deletion_email(
            confirm_url=f"https://app/confirm?token={_XSS}",
            recipient_name=None,
        )
        assert "<script>" not in html
        assert "&quot;" in html

    def test_subscription_warning_appears_when_active(self):
        _, text, html = account_deletion_email(
            confirm_url="https://app/c?t=x",
            recipient_name=None,
            has_active_subscription=True,
        )
        assert "cancel your active paid subscription" in html.lower()
        assert "no refund" in text.lower()
        assert "no refund" in html.lower()

    def test_subscription_warning_absent_when_inactive(self):
        _, text, html = account_deletion_email(
            confirm_url="https://app/c?t=x",
            recipient_name=None,
            has_active_subscription=False,
        )
        assert "no refund" not in text.lower()
        assert "no refund" not in html.lower()

    def test_destructive_disclosure_lists_each_data_class(self):
        """Users must know exactly what disappears — keep this list explicit."""
        _, text, html = account_deletion_email(
            confirm_url="https://app/c?t=x", recipient_name=None
        )
        for kind in ("patterns", "API keys", "tenant"):
            assert kind.lower() in text.lower()
            assert kind.lower() in html.lower()

    def test_recipient_name_escaped(self):
        _, _, html = account_deletion_email(
            confirm_url="https://app/c?t=x", recipient_name=_XSS_NAME
        )
        assert '<img src=x onerror="alert(1)">' not in html


# ---------------------------------------------------------------------------
# reminder_email
# ---------------------------------------------------------------------------


class TestReminderEmail:
    def test_returns_triple(self):
        subject, text, html = reminder_email(
            verify_url="https://app/verify?token=t",
            recipient_name="Alice",
            days_since_signup=7,
            days_until_delete=7,
        )
        assert subject == "Finish setting up your Engramia account"
        assert "7 days ago" in text
        assert "7 days ago" in html

    def test_days_until_delete_interpolated(self):
        _, text, html = reminder_email(
            verify_url="https://app/verify?token=t",
            recipient_name=None,
            days_since_signup=7,
            days_until_delete=14,
        )
        assert "within 14 days" in text or "within 14 days" in html
        assert "14 days" in html

    def test_url_escaped_in_href(self):
        _, _, html = reminder_email(
            verify_url=f"https://app/verify?token={_XSS}",
            recipient_name=None,
            days_since_signup=7,
            days_until_delete=7,
        )
        assert "<script>alert(1)</script>" not in html
        assert "&quot;" in html

    def test_recipient_name_escaped(self):
        _, _, html = reminder_email(
            verify_url="https://app/verify?token=t",
            recipient_name=_XSS_NAME,
            days_since_signup=7,
            days_until_delete=7,
        )
        assert '<img src=x onerror="alert(1)">' not in html


# ---------------------------------------------------------------------------
# Cross-template invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn,kwargs",
    [
        (
            verification_email,
            {"verify_url": "https://app/verify?t=x", "recipient_name": None},
        ),
        (
            account_deletion_email,
            {"confirm_url": "https://app/c?t=x", "recipient_name": None},
        ),
        (
            reminder_email,
            {
                "verify_url": "https://app/v?t=x",
                "recipient_name": None,
                "days_since_signup": 7,
                "days_until_delete": 7,
            },
        ),
    ],
)
def test_each_template_returns_three_strings(fn, kwargs):
    out = fn(**kwargs)
    assert len(out) == 3
    assert all(isinstance(p, str) and p for p in out)


@pytest.mark.parametrize(
    "fn,kwargs",
    [
        (
            verification_email,
            {"verify_url": "https://app/v?t=ok", "recipient_name": _XSS_NAME},
        ),
        (
            account_deletion_email,
            {"confirm_url": "https://app/c?t=ok", "recipient_name": _XSS_NAME},
        ),
        (
            reminder_email,
            {
                "verify_url": "https://app/v?t=ok",
                "recipient_name": _XSS_NAME,
                "days_since_signup": 7,
                "days_until_delete": 7,
            },
        ),
    ],
)
def test_no_template_renders_raw_script_tag_from_recipient_name(fn, kwargs):
    """Defence-in-depth — if a future template forgets escape() on the
    name field, this test catches it before users' inboxes do."""
    _, _, html = fn(**kwargs)
    assert "<script>" not in html
    assert 'onerror="alert' not in html
