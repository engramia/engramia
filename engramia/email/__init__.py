# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Transactional email sending.

Thin wrapper around ``smtplib`` for sending verification and notification
emails. Provider-agnostic — works with any SMTP server (Resend, Gmail,
Mailgun, Postfix, etc.) via standard env vars.
"""

from engramia.email.sender import EmailNotConfigured, send_email

__all__ = ["send_email", "EmailNotConfigured"]
