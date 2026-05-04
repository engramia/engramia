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
    credentials_email,
    reminder_email,
    verification_email,
    waitlist_ack_email,
    waitlist_admin_notify_email,
    waitlist_rejection_email,
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
        _, text, html = verification_email(verify_url="https://app/verify?token=t", recipient_name=None)
        assert text.startswith("Hi,\n\n")
        assert "<p>Hi,</p>" in html

    def test_named_recipient_uses_personal_greeting(self):
        _, text, html = verification_email(verify_url="https://app/verify?token=t", recipient_name="Bob")
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
        _, text, html = account_deletion_email(confirm_url="https://app/c?t=x", recipient_name=None)
        for kind in ("patterns", "API keys", "tenant"):
            assert kind.lower() in text.lower()
            assert kind.lower() in html.lower()

    def test_recipient_name_escaped(self):
        _, _, html = account_deletion_email(confirm_url="https://app/c?t=x", recipient_name=_XSS_NAME)
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
# waitlist_ack_email
# ---------------------------------------------------------------------------


class TestWaitlistAckEmail:
    def test_returns_triple_with_2bd_promise(self):
        subject, text, html = waitlist_ack_email(recipient_name="Alice", plan_interest="pro")
        assert subject == "We got your Engramia access request"
        assert "2 business days" in text
        assert "2 business days" in html

    def test_plan_interest_appears_in_body(self):
        _, text, html = waitlist_ack_email(recipient_name=None, plan_interest="business")
        assert "business" in text
        assert "business" in html

    def test_recipient_name_escaped(self):
        _, _, html = waitlist_ack_email(recipient_name=_XSS_NAME, plan_interest="pro")
        assert '<img src=x onerror="alert(1)">' not in html

    def test_no_name_uses_fallback_greeting(self):
        _, text, html = waitlist_ack_email(recipient_name=None, plan_interest="developer")
        assert text.startswith("Hi,\n\n")


# ---------------------------------------------------------------------------
# waitlist_admin_notify_email
# ---------------------------------------------------------------------------


class TestWaitlistAdminNotifyEmail:
    def test_subject_carries_email_and_plan(self):
        subject, _, _ = waitlist_admin_notify_email(
            request_id="req-123",
            requester_email="user@example.com",
            requester_name="Jane",
            plan_interest="pro",
            country="CZ",
            use_case="Build a docs Q&A bot",
            company_name="Acme",
            referral_source="HN",
        )
        assert "user@example.com" in subject
        assert "pro" in subject

    def test_body_contains_all_fields(self):
        _, text, html = waitlist_admin_notify_email(
            request_id="req-abc",
            requester_email="user@example.com",
            requester_name="Jane",
            plan_interest="team",
            country="DE",
            use_case="docs",
            company_name="Acme",
            referral_source="HN",
        )
        for needle in ("user@example.com", "Jane", "team", "DE", "docs", "Acme", "HN", "req-abc"):
            assert needle in text
            assert needle in html

    def test_command_hints_present(self):
        _, text, _ = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
        )
        assert "engramia waitlist approve" in text
        assert "engramia waitlist reject" in text

    def test_use_case_html_escaped(self):
        _, _, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="pro",
            country="CZ",
            use_case=_XSS,
            company_name=None,
            referral_source=None,
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_optional_fields_show_dash(self):
        _, text, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
        )
        # Em-dash for missing optional fields.
        assert "—" in text
        assert "—" in html

    def test_prod_environment_renders_full_command(self):
        """`environment=production` + full SSH target + cli prefix → real-deploy command.

        ENGRAMIA_DEPLOY_SSH_HOST holds the FULL ssh target. The template no
        longer hardcodes `deploy@` because prod/staging may use different
        users. ENGRAMIA_DEPLOY_CLI_PREFIX wraps `engramia` so a real deploy
        renders `docker exec <container> engramia ...` (the CLI ships only
        inside the API container, not on the host).
        """
        subject, text, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment="production",
            deploy_ssh_host="root@178.104.100.91",
            deploy_cli_prefix="docker exec engramia-engramia-api-1 engramia",
        )
        assert subject.startswith("[PROD]")
        assert "ssh root@178.104.100.91" in text
        assert "ssh root@178.104.100.91" in html
        # Both approve and reject must show the SSH line.
        assert text.count("ssh root@178.104.100.91") == 2
        # CLI prefix renders verbatim before the subcommand.
        assert "docker exec engramia-engramia-api-1 engramia waitlist approve req-1 --plan developer" in text
        assert "docker exec engramia-engramia-api-1 engramia waitlist reject req-1" in text
        assert "docker exec engramia-engramia-api-1 engramia waitlist approve req-1 --plan developer" in html
        # Old hardcoded `deploy@` prefix must NOT appear.
        assert "ssh deploy@" not in text
        assert "ssh deploy@" not in html
        # Placeholder must be gone.
        assert "<prod-vm>" not in text
        assert "&lt;prod-vm&gt;" not in html

    def test_staging_environment_tag_and_host(self):
        subject, text, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment="staging",
            deploy_ssh_host="root@91.99.172.242",
            deploy_cli_prefix="docker exec engramia-api-staging engramia",
        )
        assert subject.startswith("[STAGING]")
        assert "ssh root@91.99.172.242" in text
        assert "ssh root@91.99.172.242" in html
        assert "docker exec engramia-api-staging engramia waitlist approve req-1" in text
        assert "(staging)" in text  # env label in approve/reject section

    def test_host_only_target_renders_without_user(self):
        """When the env var is just a host, `ssh <host>` is what we want
        (lets ~/.ssh/config decide the user). Confirms we don't synthesise
        a user prefix."""
        _, text, _ = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment="staging",
            deploy_ssh_host="staging-api.engramia.dev",
        )
        assert "ssh staging-api.engramia.dev" in text
        assert "ssh deploy@staging-api.engramia.dev" not in text

    def test_unknown_environment_falls_back_to_placeholder(self):
        """No env vars set (dev run) → placeholder host, [ENV?] tag, plain `engramia`."""
        subject, text, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment=None,
            deploy_ssh_host=None,
            deploy_cli_prefix=None,
        )
        assert subject.startswith("[ENV?]")
        assert "ssh <unknown-vm>" in text
        assert "ssh &lt;unknown-vm&gt;" in html
        # Default CLI prefix is plain `engramia` (works for local dev where
        # the CLI is installed on PATH).
        assert "engramia waitlist approve req-1" in text
        assert "docker exec" not in text

    def test_env_set_but_host_missing_uses_env_placeholder(self):
        """Half-configured: ENGRAMIA_ENV=production but no SSH host → `<prod-vm>`."""
        _, text, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment="production",
            deploy_ssh_host=None,
        )
        assert "ssh <prod-vm>" in text
        assert "ssh &lt;prod-vm&gt;" in html

    def test_ssh_host_is_html_escaped(self):
        """Host comes from env var, but defense-in-depth — escape it anyway."""
        _, _, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment="production",
            deploy_ssh_host='evil.com"><script>alert(1)</script>',
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_cli_prefix_is_html_escaped(self):
        """CLI prefix comes from env var too — must be escaped in HTML."""
        _, _, html = waitlist_admin_notify_email(
            request_id="req-1",
            requester_email="u@e.cz",
            requester_name="X",
            plan_interest="developer",
            country="CZ",
            use_case=None,
            company_name=None,
            referral_source=None,
            environment="production",
            deploy_ssh_host="root@1.2.3.4",
            deploy_cli_prefix='engramia"><script>alert(1)</script>',
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# credentials_email
# ---------------------------------------------------------------------------


class TestCredentialsEmail:
    def test_password_present_in_text_and_html(self):
        _, text, html = credentials_email(
            recipient_name="Alice",
            login_email="alice@example.com",
            one_time_password="OneTimePassXYZ",
            dashboard_url="https://app.engramia.dev",
            plan_tier="pro",
        )
        assert "OneTimePassXYZ" in text
        assert "OneTimePassXYZ" in html

    def test_force_change_warning_present(self):
        _, text, html = credentials_email(
            recipient_name=None,
            login_email="x@e.cz",
            one_time_password="pw",
            dashboard_url="https://app.engramia.dev",
            plan_tier="developer",
        )
        assert "one-time" in text.lower()
        assert "one-time" in html.lower()
        assert "set a new" in text.lower() or "set a new" in html.lower()

    def test_dashboard_url_html_escaped(self):
        _, _, html = credentials_email(
            recipient_name=None,
            login_email="u@e.cz",
            one_time_password="pw",
            dashboard_url=f"https://app{_XSS}",
            plan_tier="pro",
        )
        assert "<script>alert(1)</script>" not in html
        assert "&quot;" in html

    def test_recipient_name_escaped(self):
        _, _, html = credentials_email(
            recipient_name=_XSS_NAME,
            login_email="u@e.cz",
            one_time_password="pw",
            dashboard_url="https://app.engramia.dev",
            plan_tier="pro",
        )
        assert '<img src=x onerror="alert(1)">' not in html

    def test_password_html_escaped_too(self):
        """Auto-generated password contains URL-safe chars but defence-in-depth."""
        _, _, html = credentials_email(
            recipient_name=None,
            login_email="u@e.cz",
            one_time_password="<script>x</script>",
            dashboard_url="https://app.engramia.dev",
            plan_tier="pro",
        )
        assert "<script>x</script>" not in html

    def test_plan_tier_visible(self):
        _, text, html = credentials_email(
            recipient_name=None,
            login_email="u@e.cz",
            one_time_password="pw",
            dashboard_url="https://app.engramia.dev",
            plan_tier="business",
        )
        assert "business" in text
        assert "business" in html


# ---------------------------------------------------------------------------
# waitlist_rejection_email
# ---------------------------------------------------------------------------


class TestWaitlistRejectionEmail:
    def test_reason_interpolated_in_body(self):
        _, text, html = waitlist_rejection_email(
            recipient_name="Bob",
            reason="Engramia isn't a fit for purely on-prem deployments yet.",
        )
        assert "on-prem deployments" in text
        assert "on-prem deployments" in html

    def test_reason_html_escaped(self):
        _, _, html = waitlist_rejection_email(
            recipient_name=None,
            reason=_XSS,
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_recipient_name_escaped(self):
        _, _, html = waitlist_rejection_email(
            recipient_name=_XSS_NAME,
            reason="any",
        )
        assert '<img src=x onerror="alert(1)">' not in html

    def test_reapply_link_present(self):
        _, text, html = waitlist_rejection_email(recipient_name=None, reason="any reason")
        # Encourage re-application — reduces customer churn perception.
        assert "submit a new request" in text.lower() or "request-access" in html


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
