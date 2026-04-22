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
