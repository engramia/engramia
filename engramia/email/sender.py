# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""SMTP email sender.

Config via env vars:
    ENGRAMIA_SMTP_HOST      (required)
    ENGRAMIA_SMTP_PORT      (default: 587)
    ENGRAMIA_SMTP_USER      (required when SMTP server requires auth)
    ENGRAMIA_SMTP_PASSWORD  (required when SMTP server requires auth)
    ENGRAMIA_SMTP_FROM      (required — sender email, e.g. noreply@example.com)
    ENGRAMIA_SMTP_USE_TLS   (default: true — STARTTLS on port 587; set to
                            'false' for port 25; use port 465 for implicit TLS)

When ENGRAMIA_SMTP_HOST is unset, ``send_email`` raises ``EmailNotConfigured``.
Callers that want to degrade gracefully (registration, cleanup) should catch it
and log a warning; callers that require delivery (e.g. a CLI test command)
should let it propagate.
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

_log = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    """Raised when SMTP env vars are not set."""


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    reply_to: str | None = None,
) -> None:
    """Send an email via SMTP. Blocks until the server ACKs or raises.

    Args:
        reply_to: Optional Reply-To header. Use when the From sender is a
            noreply alias but replies should land elsewhere (e.g. founder
            inbox for pilot-program acks).

    Raises:
        EmailNotConfigured: SMTP host not set.
        smtplib.SMTPException: on any SMTP-level failure (connection, auth,
            recipient rejected). Callers should handle this for graceful
            degradation where appropriate.
    """
    host = os.environ.get("ENGRAMIA_SMTP_HOST", "").strip()
    if not host:
        raise EmailNotConfigured("ENGRAMIA_SMTP_HOST is not set. Configure SMTP to enable transactional email.")

    port = int(os.environ.get("ENGRAMIA_SMTP_PORT", "587"))
    user = os.environ.get("ENGRAMIA_SMTP_USER", "").strip()
    password = os.environ.get("ENGRAMIA_SMTP_PASSWORD", "")
    sender = os.environ.get("ENGRAMIA_SMTP_FROM", "").strip()
    use_tls = _truthy(os.environ.get("ENGRAMIA_SMTP_USE_TLS", "true"))

    if not sender:
        raise EmailNotConfigured("ENGRAMIA_SMTP_FROM is not set.")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    # Port 465 is implicit TLS (SMTPS); 587 is STARTTLS upgrade on plaintext.
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            if use_tls:
                s.starttls(context=ctx)
                s.ehlo()
            if user:
                s.login(user, password)
            s.send_message(msg)

    _log.info("Email sent: to=%s subject=%r", to, subject)
