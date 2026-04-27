# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Inline email templates for Engramia transactional mail.

No Jinja or template engine — plain f-strings keep the dependency surface
zero and make the rendered output trivially reviewable.
"""

from html import escape


def verification_email(
    *,
    verify_url: str,
    recipient_name: str | None,
    expires_hours: int = 24,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a verification email."""
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)
    safe_url = escape(verify_url, quote=True)

    subject = "Verify your Engramia account"
    text = (
        f"{greeting}\n\n"
        "Thanks for signing up for Engramia. Please verify your email address by "
        f"opening this link (valid for {expires_hours} hours):\n\n"
        f"{verify_url}\n\n"
        "If you didn't create an Engramia account, you can safely ignore this email.\n\n"
        "— The Engramia team\n"
    )
    html = f"""<!doctype html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#1a1d27; max-width:540px; margin:0 auto; padding:24px;">
  <p>{safe_greeting}</p>
  <p>Thanks for signing up for <strong>Engramia</strong>. Please confirm your email address to finish creating your account.</p>
  <p style="margin:24px 0;">
    <a href="{safe_url}" style="display:inline-block; background:#4f46e5; color:#ffffff; padding:12px 20px; border-radius:8px; text-decoration:none; font-weight:600;">Verify my email</a>
  </p>
  <p style="color:#64748b; font-size:13px;">Or paste this link into your browser: <br><span style="word-break:break-all;">{safe_url}</span></p>
  <p style="color:#64748b; font-size:13px;">This link expires in {expires_hours} hours. If you didn't create an account, you can ignore this email.</p>
  <p style="color:#94a3b8; font-size:12px; margin-top:32px;">— The Engramia team</p>
</body>
</html>
"""
    return subject, text, html


def account_deletion_email(
    *,
    confirm_url: str,
    recipient_name: str | None,
    expires_hours: int = 24,
    has_active_subscription: bool = False,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for an account deletion confirmation email.

    The link in the email is the only way to actually trigger deletion — the
    /v1/me/deletion-request endpoint just generates the token. This double-opt-in
    protects against session hijacking and accidental clicks in the dashboard.
    """
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)
    safe_url = escape(confirm_url, quote=True)

    subject = "Confirm Engramia account deletion"

    sub_warning_text = (
        "\nNote: this will also CANCEL your active paid subscription with no refund "
        "for the remainder of the billing period.\n"
        if has_active_subscription
        else ""
    )
    sub_warning_html = (
        '<p style="color:#b91c1c; font-size:14px;"><strong>This will also cancel '
        "your active paid subscription</strong> with no refund for the remainder "
        "of the billing period.</p>"
        if has_active_subscription
        else ""
    )

    text = (
        f"{greeting}\n\n"
        "We received a request to delete your Engramia account. To confirm, "
        f"open this link within {expires_hours} hours:\n\n"
        f"{confirm_url}\n\n"
        "Clicking the link will permanently delete your account and ALL associated data:\n"
        "  - All patterns, embeddings, jobs, and audit detail\n"
        "  - All API keys and active sessions\n"
        "  - Your tenant and projects\n"
        f"{sub_warning_text}"
        "\n"
        "This action cannot be undone. If you didn't request this, you can safely "
        "ignore this email — the link will expire automatically.\n\n"
        "— The Engramia team\n"
    )
    html = f"""<!doctype html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#1a1d27; max-width:540px; margin:0 auto; padding:24px;">
  <p>{safe_greeting}</p>
  <p>We received a request to delete your <strong>Engramia</strong> account. To confirm, click the button below within {expires_hours} hours.</p>
  <p style="margin:24px 0;">
    <a href="{safe_url}" style="display:inline-block; background:#b91c1c; color:#ffffff; padding:12px 20px; border-radius:8px; text-decoration:none; font-weight:600;">Confirm account deletion</a>
  </p>
  <p style="color:#64748b; font-size:13px;">Or paste this link into your browser: <br><span style="word-break:break-all;">{safe_url}</span></p>
  <p style="color:#1a1d27; font-size:14px;"><strong>Clicking the link will permanently delete:</strong></p>
  <ul style="color:#1a1d27; font-size:14px;">
    <li>All patterns, embeddings, jobs, and audit detail</li>
    <li>All API keys and active sessions</li>
    <li>Your tenant and projects</li>
  </ul>
  {sub_warning_html}
  <p style="color:#64748b; font-size:13px;">This action cannot be undone. If you didn't request this, you can safely ignore this email — the link will expire in {expires_hours} hours.</p>
  <p style="color:#94a3b8; font-size:12px; margin-top:32px;">— The Engramia team</p>
</body>
</html>
"""
    return subject, text, html


def reminder_email(
    *,
    verify_url: str,
    recipient_name: str | None,
    days_since_signup: int,
    days_until_delete: int,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a cleanup reminder email."""
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)
    safe_url = escape(verify_url, quote=True)

    subject = "Finish setting up your Engramia account"
    text = (
        f"{greeting}\n\n"
        f"You signed up for Engramia {days_since_signup} days ago but haven't confirmed "
        "your email address yet. Here's your verification link:\n\n"
        f"{verify_url}\n\n"
        f"If we don't hear from you within {days_until_delete} days, we'll delete the "
        "pending account to keep our systems tidy. You can always sign up again later.\n\n"
        "— The Engramia team\n"
    )
    html = f"""<!doctype html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#1a1d27; max-width:540px; margin:0 auto; padding:24px;">
  <p>{safe_greeting}</p>
  <p>You signed up for <strong>Engramia</strong> {days_since_signup} days ago but haven't confirmed your email yet.</p>
  <p style="margin:24px 0;">
    <a href="{safe_url}" style="display:inline-block; background:#4f46e5; color:#ffffff; padding:12px 20px; border-radius:8px; text-decoration:none; font-weight:600;">Verify my email</a>
  </p>
  <p style="color:#64748b; font-size:13px;">Or paste this link into your browser: <br><span style="word-break:break-all;">{safe_url}</span></p>
  <p style="color:#64748b; font-size:13px;">If you don't confirm within {days_until_delete} days, we'll delete the pending account.</p>
  <p style="color:#94a3b8; font-size:12px; margin-top:32px;">— The Engramia team</p>
</body>
</html>
"""
    return subject, text, html
