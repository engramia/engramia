# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Inline email templates for Engramia transactional mail.

No Jinja or template engine — plain f-strings keep the dependency surface
zero and make the rendered output trivially reviewable.

All customer-facing HTML emails share the chrome produced by
``_email_layout()``: a centred 600-px white card on a soft off-white
background, an ``engram·ia`` wordmark header, system font stack, and a
footer with the marketing-site link plus privacy / support links.
Inline styles only — no ``<style>`` blocks, no flexbox, no media
queries — so the rendering stays consistent across Gmail / Outlook /
Apple Mail / mobile clients.

The internal admin notification (``waitlist_admin_notify_email``) is
deliberately *not* dressed in the customer chrome: it goes to
support@engramia.dev with copy-paste-ready ssh + docker exec lines, and
extra branding would just push the actionable content below the fold.
"""

from html import escape

# ---------------------------------------------------------------------------
# Branded layout — shared by every customer-facing HTML email.
# ---------------------------------------------------------------------------

#: Marketing-site brand tokens, mirrored manually from
#: ``Website/src/styles/globals.css``. They diverge from the marketing
#: site's *dark* surface palette on purpose: emails render reliably only
#: in light mode (Outlook + most webmail strip dark-mode overrides), so
#: the card is white with the same accent purple for emphasis.
_BRAND_ACCENT = "#6B5DC8"
_BRAND_ACCENT_DARK = "#5040a3"  # used when text-on-light needs more contrast
_PAGE_BG = "#f4f5fa"
_CARD_BG = "#ffffff"
_TEXT_PRIMARY = "#1a1d27"
_TEXT_BODY = "#3a4150"
_TEXT_MUTED = "#6b7280"
_TEXT_SUBTLE = "#9ca3af"
_BORDER_SUBTLE = "#e7e9ee"
_DANGER = "#b91c1c"
_FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"

#: Marketing site URL used in the wordmark href and the footer link.
_MARKETING_URL = "https://engramia.dev"
_PRIVACY_URL = "https://engramia.dev/legal/privacy-policy"
_SUPPORT_EMAIL = "support@engramia.dev"


def _email_layout(*, content_html: str, preheader: str = "") -> str:
    """Wrap inner HTML content in the standard branded chrome.

    ``preheader`` is the snippet most webmail clients show next to the
    subject in the inbox preview — keep it short (≤ 90 chars) and
    information-dense. The hidden div trick (display:none + max-height:0
    + zero-width spaces padding) prevents the rest of the body from
    leaking into the preview.
    """
    safe_preheader = escape(preheader)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>Engramia</title>
</head>
<body style="margin:0; padding:0; background-color:{_PAGE_BG}; font-family:{_FONT_STACK}; color:{_TEXT_BODY}; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%;">
  <div style="display:none; max-height:0; overflow:hidden; mso-hide:all; visibility:hidden; opacity:0; color:transparent; font-size:1px; line-height:1px;">
    {safe_preheader}&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
  </div>
  <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="background-color:{_PAGE_BG}; padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" border="0" cellpadding="0" cellspacing="0" style="max-width:600px; width:100%; background-color:{_CARD_BG}; border-radius:14px; box-shadow:0 1px 3px rgba(15,17,23,0.06), 0 1px 2px rgba(15,17,23,0.04); border:1px solid {_BORDER_SUBTLE};">
          <tr>
            <td style="padding:32px 40px 8px 40px;">
              <a href="{_MARKETING_URL}" style="text-decoration:none; color:{_TEXT_PRIMARY};">
                <span style="font-size:26px; font-weight:700; letter-spacing:-0.02em; color:{_TEXT_PRIMARY};">engram<span style="color:{_BRAND_ACCENT};">ia</span></span>
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 40px 32px 40px; font-size:15px; line-height:1.6; color:{_TEXT_BODY};">
              {content_html}
            </td>
          </tr>
          <tr>
            <td style="padding:20px 40px 24px 40px; border-top:1px solid {_BORDER_SUBTLE}; font-size:12px; line-height:1.5; color:{_TEXT_SUBTLE};">
              <p style="margin:0 0 6px 0; color:{_TEXT_MUTED};">Engramia — reusable agent execution memory and evaluation.</p>
              <p style="margin:0;">
                <a href="{_MARKETING_URL}" style="color:{_TEXT_MUTED}; text-decoration:underline;">engramia.dev</a>
                &nbsp;·&nbsp;
                <a href="{_PRIVACY_URL}" style="color:{_TEXT_MUTED}; text-decoration:underline;">Privacy</a>
                &nbsp;·&nbsp;
                <a href="mailto:{_SUPPORT_EMAIL}" style="color:{_TEXT_MUTED}; text-decoration:underline;">Support</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _button_html(*, href: str, label: str, danger: bool = False) -> str:
    """Render a CTA button compatible with Outlook (table-wrapped, inline styles).

    ``danger=True`` swaps the accent purple for a destructive red — used
    for the account-deletion confirmation. Outlook ignores ``border-radius``
    on anchor tags but still renders the colour and padding, so the
    button degrades to a coloured rectangle there (acceptable).
    """
    bg = _DANGER if danger else _BRAND_ACCENT
    safe_label = escape(label)
    safe_href = escape(href, quote=True)
    return (
        '<table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin:8px 0;">'
        "<tr>"
        f'<td style="background-color:{bg}; border-radius:10px;">'
        f'<a href="{safe_href}" style="display:inline-block; padding:12px 22px; '
        f"font-family:{_FONT_STACK}; font-size:15px; font-weight:600; color:#ffffff; "
        f'text-decoration:none; border-radius:10px;">{safe_label}</a>'
        "</td>"
        "</tr>"
        "</table>"
    )


# ---------------------------------------------------------------------------
# Customer-facing templates
# ---------------------------------------------------------------------------


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
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">Thanks for signing up for <strong>Engramia</strong>. Please confirm your email address to finish creating your account.</p>
      {_button_html(href=verify_url, label="Verify my email")}
      <p style="margin:16px 0 8px 0; color:{_TEXT_MUTED}; font-size:13px;">Or paste this link into your browser:</p>
      <p style="margin:0 0 24px 0; word-break:break-all;"><a href="{safe_url}" style="color:{_BRAND_ACCENT_DARK}; text-decoration:underline; font-size:13px;">{safe_url}</a></p>
      <p style="margin:0; color:{_TEXT_MUTED}; font-size:13px;">This link expires in {expires_hours} hours. If you didn't create an account, you can ignore this email.</p>
    """
    html = _email_layout(
        content_html=content,
        preheader="Confirm your email to finish creating your Engramia account.",
    )
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
        f'<p style="margin:0 0 16px 0; color:{_DANGER}; font-size:14px;"><strong>This will also cancel '
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
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">We received a request to delete your <strong>Engramia</strong> account. To confirm, click the button below within {expires_hours} hours.</p>
      {_button_html(href=confirm_url, label="Confirm account deletion", danger=True)}
      <p style="margin:16px 0 8px 0; color:{_TEXT_MUTED}; font-size:13px;">Or paste this link into your browser:</p>
      <p style="margin:0 0 24px 0; word-break:break-all;"><a href="{safe_url}" style="color:{_BRAND_ACCENT_DARK}; text-decoration:underline; font-size:13px;">{safe_url}</a></p>
      <p style="margin:0 0 8px 0; color:{_TEXT_PRIMARY}; font-size:14px;"><strong>Clicking the link will permanently delete:</strong></p>
      <ul style="margin:0 0 16px 0; padding-left:20px; color:{_TEXT_BODY}; font-size:14px; line-height:1.6;">
        <li>All patterns, embeddings, jobs, and audit detail</li>
        <li>All API keys and active sessions</li>
        <li>Your tenant and projects</li>
      </ul>
      {sub_warning_html}
      <p style="margin:0; color:{_TEXT_MUTED}; font-size:13px;">This action cannot be undone. If you didn't request this, you can safely ignore this email — the link will expire in {expires_hours} hours.</p>
    """
    html = _email_layout(
        content_html=content,
        preheader=f"Confirm deletion within {expires_hours} hours. Otherwise the link expires automatically.",
    )
    return subject, text, html


def waitlist_ack_email(
    *,
    recipient_name: str | None,
    plan_interest: str,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the access-request ack email.

    Sent immediately on form submit to set expectations: we'll review and reply
    within 2 business days. The 2BD promise is also encoded in the
    ``waitlist_pending_age_seconds`` Prometheus alert threshold (48h).
    """
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)
    safe_plan = escape(plan_interest)

    subject = "We got your Engramia access request"
    text = (
        f"{greeting}\n\n"
        "Thanks for requesting access to Engramia. We received your submission and "
        f"will review it within 2 business days.\n\n"
        f"You requested the {plan_interest} plan. If we have any further questions "
        "we will contact you on this email.\n\n"
        "Thank you for your interest\n"
        "Marek from Engramia\n"
    )
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">Thanks for requesting access to <strong>Engramia</strong>. We received your submission and will review it within <strong>2 business days</strong>.</p>
      <p style="margin:0 0 16px 0;">You requested the <strong>{safe_plan}</strong> plan. If we have any further questions we will contact you on this email.</p>
      <p style="margin:24px 0 0 0; color:{_TEXT_MUTED}; font-size:14px;">Thank you for your interest,<br>Marek from Engramia</p>
    """
    html = _email_layout(
        content_html=content,
        preheader="Thanks for requesting access — we'll review within 2 business days.",
    )
    return subject, text, html


def waitlist_pilot_ack_email(
    *,
    recipient_name: str | None,
    segment: str,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the Pilot Program ack email.

    Sent to applicants whose ``referral_source`` starts with ``pilot-`` (the
    Website's /pilot form tags submissions this way). The cross-link in the
    body is shaped to the segment they self-selected so the email signals
    we read the application before the human review.

    The caller is expected to set ``Reply-To: pilot@engramia.dev`` on the
    SMTP message so applicants reach the founder directly, not the generic
    support queue.
    """
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)

    # Per-segment cross-link — the *one* page most likely to address the
    # applicant's underlying question while they wait. Falls back to two
    # links for ``pilot-other`` or unrecognised segment values.
    segment_links_text: dict[str, str] = {
        "eu-compliance": (
            "  EU compliance brief — GDPR Art. 17/20 mapping, audit log\n"
            "  alignment with EU AI Act Art. 12, DPA template:\n"
            "  https://engramia.dev/eu-compliance"
        ),
        "openai-migration": (
            "  OpenAI Assistants migration path — drop-in replacement\n"
            "  for thread persistence and the multi-LLM extension before\n"
            "  the Aug 2026 sunset:\n"
            "  https://engramia.dev/migrate/openai-assistants"
        ),
        "custom-memory": (
            "  LongMemEval benchmark results — Engramia 97.8% with\n"
            "  per-dimension breakdown vs. custom-memory baselines:\n"
            "  https://engramia.dev/benchmarks"
        ),
    }
    segment_link_text = segment_links_text.get(
        segment,
        "  EU compliance brief: https://engramia.dev/eu-compliance\n"
        "  OpenAI Assistants migration: https://engramia.dev/migrate/openai-assistants",
    )

    segment_links_html: dict[str, str] = {
        "eu-compliance": (
            f'<p style="margin:0;"><a href="https://engramia.dev/eu-compliance" '
            f'style="color:{_BRAND_ACCENT_DARK}; text-decoration:none; font-weight:600;">'
            "EU compliance brief</a> — GDPR Art. 17/20 mapping, audit log "
            "alignment with EU AI Act Art. 12, DPA template.</p>"
        ),
        "openai-migration": (
            f'<p style="margin:0;"><a href="https://engramia.dev/migrate/openai-assistants" '
            f'style="color:{_BRAND_ACCENT_DARK}; text-decoration:none; font-weight:600;">'
            "OpenAI Assistants migration path</a> — drop-in replacement for "
            "thread persistence and the multi-LLM extension before the Aug 2026 sunset.</p>"
        ),
        "custom-memory": (
            f'<p style="margin:0;"><a href="https://engramia.dev/benchmarks" '
            f'style="color:{_BRAND_ACCENT_DARK}; text-decoration:none; font-weight:600;">'
            "LongMemEval benchmark results</a> — Engramia 97.8% with full "
            "per-dimension breakdown vs. custom-memory baselines.</p>"
        ),
    }
    segment_link_html = segment_links_html.get(
        segment,
        f'<p style="margin:0 0 8px 0;"><a href="https://engramia.dev/eu-compliance" '
        f'style="color:{_BRAND_ACCENT_DARK}; text-decoration:none; font-weight:600;">EU compliance brief</a></p>'
        f'<p style="margin:0;"><a href="https://engramia.dev/migrate/openai-assistants" '
        f'style="color:{_BRAND_ACCENT_DARK}; text-decoration:none; font-weight:600;">OpenAI Assistants migration path</a></p>',
    )

    subject = "Engramia Pilot — application received"
    text = (
        f"{greeting}\n\n"
        "Thanks for applying to the Engramia Pilot Program. I read every "
        "application personally — yours is in the queue.\n\n"
        "Here's what happens next:\n\n"
        "1. I review your application against the segment seats still open.\n"
        "   You hear back within 5 business days.\n\n"
        "2. If we are a match, I email you to book a 30-minute intro call.\n"
        "   We discuss your migration path, timeline, and what success looks\n"
        "   like for the first three months.\n\n"
        "3. After the call, you either get an onboarding slot (start within\n"
        '   5 business days) or a clear "not a fit, here is why" — never silence.\n\n'
        "While you wait, this might be useful in your context:\n\n"
        f"{segment_link_text}\n\n"
        "Anything urgent or unclear? Reply directly to this email — it\n"
        "reaches me, not a queue.\n\n"
        "Marek\n"
    )
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">Thanks for applying to the <strong>Engramia Pilot Program</strong>. I read every application personally — yours is in the queue.</p>
      <p style="margin:16px 0 8px 0;"><strong>Here's what happens next:</strong></p>
      <ol style="padding-left:20px; margin:0 0 16px 0; line-height:1.6;">
        <li style="margin-bottom:10px;">I review your application against the segment seats still open. You hear back within <strong>5 business days</strong>.</li>
        <li style="margin-bottom:10px;">If we are a match, I email you to book a 30-minute intro call. We discuss your migration path, timeline, and what success looks like for the first three months.</li>
        <li style="margin-bottom:10px;">After the call, you either get an onboarding slot (start within 5 business days) or a clear "not a fit, here is why" — <strong>never silence</strong>.</li>
      </ol>
      <p style="margin:24px 0 8px 0;"><strong>While you wait,</strong> this might be useful in your context:</p>
      <div style="background:{_PAGE_BG}; border-left:3px solid {_BRAND_ACCENT}; padding:12px 16px; border-radius:0 6px 6px 0;">
        {segment_link_html}
      </div>
      <p style="margin:24px 0 0 0;">Anything urgent or unclear? Reply directly to this email — it reaches me, not a queue.</p>
      <p style="margin:24px 0 0 0;">Marek</p>
    """
    html = _email_layout(
        content_html=content,
        preheader="I read every Pilot application personally — yours is in the queue.",
    )
    return subject, text, html


# ---------------------------------------------------------------------------
# Internal admin notification (NOT customer-facing — no branded chrome)
# ---------------------------------------------------------------------------


def _normalize_environment(environment: str | None) -> str:
    """Map raw `ENGRAMIA_ENV` values to a stable label used in email subjects.

    Returns "prod" / "staging" / "unknown". The "unknown" branch is taken in
    dev/local runs where the env var is unset — we still render the email with
    placeholder hostnames so the operator can spot the misconfiguration.
    """
    if not environment:
        return "unknown"
    env = environment.strip().lower()
    if env in ("production", "prod"):
        return "prod"
    if env == "staging":
        return "staging"
    return "unknown"


def waitlist_admin_notify_email(
    *,
    request_id: str,
    requester_email: str,
    requester_name: str,
    plan_interest: str,
    country: str,
    use_case: str | None,
    company_name: str | None,
    referral_source: str | None,
    environment: str | None = None,
    deploy_ssh_host: str | None = None,
    deploy_cli_prefix: str | None = None,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the admin notification email.

    Sent to the admin (support@engramia.dev) on every form submit so they can
    triage without having to poll the CLI. Body is informational only — the
    actual provisioning happens via the CLI on the prod VM.

    ``environment`` should be ``ENGRAMIA_ENV`` ("production" / "staging");
    ``deploy_ssh_host`` should be ``ENGRAMIA_DEPLOY_SSH_HOST`` — the **full
    SSH target** the operator copy-pastes (``user@host`` or just ``host`` if
    the SSH config picks the user). The template no longer hardcodes a
    ``deploy@`` prefix because production and staging may run as different
    users (e.g. ``root@<ip>``).

    ``deploy_cli_prefix`` should be ``ENGRAMIA_DEPLOY_CLI_PREFIX`` — the
    invocation rendered verbatim before ``waitlist approve|reject``. The CLI
    itself ships only inside the API container, so on a real deploy this
    needs ``docker exec <container> engramia`` (container name varies per
    env: ``engramia-api-staging`` vs ``engramia-engramia-api-1`` on prod).
    Defaults to plain ``engramia`` for local dev where the CLI is on PATH.

    All three are optional; when missing, the email keeps placeholders so
    dev runs still render.

    This template is deliberately *not* wrapped in the customer-facing
    branded chrome — it's an internal triage email, copy-paste-ready for
    the operator on call. Branding here would just push the actionable
    ssh + docker exec lines below the fold.
    """
    env_label = _normalize_environment(environment)
    env_tag = {"prod": "[PROD]", "staging": "[STAGING]", "unknown": "[ENV?]"}[env_label]
    ssh_target = (deploy_ssh_host or "").strip() or f"<{env_label}-vm>"
    cli_prefix = (deploy_cli_prefix or "").strip() or "engramia"

    safe_email = escape(requester_email)
    safe_name = escape(requester_name)
    safe_plan = escape(plan_interest)
    safe_country = escape(country)
    safe_use_case = escape(use_case or "—")
    safe_company = escape(company_name or "—")
    safe_referral = escape(referral_source or "—")
    safe_request_id = escape(request_id)
    safe_ssh_target = escape(ssh_target)
    safe_cli_prefix = escape(cli_prefix)
    safe_env_tag = escape(env_tag)

    subject = f"{env_tag} New waitlist: {requester_email} ({plan_interest})"
    text = (
        f"New access request ({env_label}):\n\n"
        f"  Request ID:    {request_id}\n"
        f"  Email:         {requester_email}\n"
        f"  Name:          {requester_name}\n"
        f"  Plan interest: {plan_interest}\n"
        f"  Company:       {company_name or '—'}\n"
        f"  Country:       {country}\n"
        f"  Referral:      {referral_source or '—'}\n"
        f"  Use case:      {use_case or '—'}\n\n"
        f"To approve ({env_label}):\n"
        f"  ssh {ssh_target}\n"
        f"  {cli_prefix} waitlist approve {request_id} --plan {plan_interest}\n\n"
        f"To reject ({env_label}):\n"
        f"  ssh {ssh_target}\n"
        f'  {cli_prefix} waitlist reject {request_id} --reason "<your reason here>"\n'
    )
    html = f"""<!doctype html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color:#1a1d27; max-width:640px; margin:0 auto; padding:24px;">
  <h2 style="margin-top:0;">New waitlist request <span style="font-size:13px; color:#64748b; font-weight:500;">{safe_env_tag}</span></h2>
  <table style="border-collapse:collapse; width:100%;">
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Request&nbsp;ID</td><td style="padding:6px 0; font-family:monospace;">{safe_request_id}</td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Email</td><td style="padding:6px 0;">{safe_email}</td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Name</td><td style="padding:6px 0;">{safe_name}</td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Plan&nbsp;interest</td><td style="padding:6px 0;"><strong>{safe_plan}</strong></td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Country</td><td style="padding:6px 0;">{safe_country}</td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Company</td><td style="padding:6px 0;">{safe_company}</td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Referral</td><td style="padding:6px 0;">{safe_referral}</td></tr>
    <tr><td style="padding:6px 12px 6px 0; color:#64748b; vertical-align:top;">Use&nbsp;case</td><td style="padding:6px 0; white-space:pre-wrap;">{safe_use_case}</td></tr>
  </table>
  <p style="margin-top:24px;">To approve ({safe_env_tag}):</p>
  <pre style="background:#f8fafc; padding:12px; border-radius:6px; font-size:12px; overflow-x:auto;">ssh {safe_ssh_target}
{safe_cli_prefix} waitlist approve {safe_request_id} --plan {safe_plan}</pre>
  <p>To reject ({safe_env_tag}):</p>
  <pre style="background:#f8fafc; padding:12px; border-radius:6px; font-size:12px; overflow-x:auto;">ssh {safe_ssh_target}
{safe_cli_prefix} waitlist reject {safe_request_id} --reason "&lt;your reason&gt;"</pre>
</body>
</html>
"""
    return subject, text, html


# ---------------------------------------------------------------------------
# More customer-facing templates (continued)
# ---------------------------------------------------------------------------


def credentials_email(
    *,
    recipient_name: str | None,
    login_email: str,
    one_time_password: str,
    dashboard_url: str,
    plan_tier: str,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the manual-onboarding credentials email.

    Sent on ``engramia waitlist approve``. The plaintext password is one-time —
    the user is forced to change it on first login (`must_change_password=true`
    on the cloud_users row, see ADR-007).
    """
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)
    safe_email = escape(login_email)
    safe_pw = escape(one_time_password)
    safe_url = escape(dashboard_url, quote=True)
    safe_plan = escape(plan_tier)

    subject = "Your Engramia account is ready"
    text = (
        f"{greeting}\n\n"
        f"Your Engramia {plan_tier} account is provisioned and ready to use.\n\n"
        f"Login:    {dashboard_url}/login\n"
        f"Email:    {login_email}\n"
        f"Password: {one_time_password}\n\n"
        "IMPORTANT — security:\n"
        "This is a one-time password. On your first login the dashboard will "
        "prompt you to set a new one before you can access the rest of the app. "
        "Please log in within 24 hours and complete the change so this password "
        "stops working.\n\n"
        "If you didn't request this account, please reply and we'll delete it.\n\n"
        "— The Engramia team\n"
    )
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">Your Engramia <strong>{safe_plan}</strong> account is provisioned and ready to use.</p>
      <table role="presentation" style="border-collapse:collapse; width:100%; margin:16px 0; background:{_PAGE_BG}; border-radius:10px; border:1px solid {_BORDER_SUBTLE};">
        <tr>
          <td style="padding:12px 16px; color:{_TEXT_MUTED}; font-size:13px; width:90px; border-bottom:1px solid {_BORDER_SUBTLE};">Login</td>
          <td style="padding:12px 16px; font-size:14px; border-bottom:1px solid {_BORDER_SUBTLE};"><a href="{safe_url}/login" style="color:{_BRAND_ACCENT_DARK}; text-decoration:underline;">{safe_url}/login</a></td>
        </tr>
        <tr>
          <td style="padding:12px 16px; color:{_TEXT_MUTED}; font-size:13px; border-bottom:1px solid {_BORDER_SUBTLE};">Email</td>
          <td style="padding:12px 16px; font-family:'SFMono-Regular', Menlo, Consolas, monospace; font-size:14px; border-bottom:1px solid {_BORDER_SUBTLE};">{safe_email}</td>
        </tr>
        <tr>
          <td style="padding:12px 16px; color:{_TEXT_MUTED}; font-size:13px;">Password</td>
          <td style="padding:12px 16px; font-family:'SFMono-Regular', Menlo, Consolas, monospace; font-size:14px;">{safe_pw}</td>
        </tr>
      </table>
      {_button_html(href=f"{dashboard_url}/login", label="Log in to Engramia")}
      <p style="margin:16px 0 8px 0; padding:12px 16px; background:#fef2f2; border-left:3px solid {_DANGER}; border-radius:0 6px 6px 0; color:{_TEXT_PRIMARY}; font-size:14px;"><strong style="color:{_DANGER};">Important — security:</strong> This is a one-time password. On your first login the dashboard will prompt you to set a new one before you can access the rest of the app. Please log in within 24 hours and complete the change.</p>
      <p style="margin:16px 0 0 0; color:{_TEXT_MUTED}; font-size:13px;">If you didn't request this account, please reply and we'll delete it.</p>
    """
    html = _email_layout(
        content_html=content,
        preheader=f"Your Engramia {plan_tier} account is ready — log in within 24 hours.",
    )
    return subject, text, html


def waitlist_rejection_email(
    *,
    recipient_name: str | None,
    reason: str,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for the waitlist rejection email.

    The ``reason`` text is supplied by the admin via
    ``engramia waitlist reject <id> --reason "<text>"`` (see ADR-008). The
    template wraps it in a polite frame; the admin is expected to draft the
    case-specific wording out-of-band before invoking the CLI.
    """
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    safe_greeting = escape(greeting)
    safe_reason = escape(reason)

    subject = "Update on your Engramia access request"
    text = (
        f"{greeting}\n\n"
        "Thanks again for your interest in Engramia. After reviewing your "
        "request, we won't be able to onboard you at this time.\n\n"
        f"{reason}\n\n"
        "If your situation changes — different use case, different scale, "
        "different region — please feel free to submit a new request. We'd be "
        "happy to take another look.\n\n"
        "— The Engramia team\n"
    )
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">Thanks again for your interest in <strong>Engramia</strong>. After reviewing your request, we won't be able to onboard you at this time.</p>
      <p style="margin:16px 0; padding:12px 16px; background:{_PAGE_BG}; border-left:3px solid {_TEXT_SUBTLE}; border-radius:0 6px 6px 0; white-space:pre-wrap; color:{_TEXT_PRIMARY};">{safe_reason}</p>
      <p style="margin:16px 0 0 0;">If your situation changes — different use case, different scale, different region — please feel free to <a href="https://engramia.dev/request-access" style="color:{_BRAND_ACCENT_DARK}; text-decoration:underline;">submit a new request</a>. We'd be happy to take another look.</p>
    """
    html = _email_layout(
        content_html=content,
        preheader="Update on your Engramia access request.",
    )
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
    content = f"""
      <p style="margin:0 0 16px 0;">{safe_greeting}</p>
      <p style="margin:0 0 16px 0;">You signed up for <strong>Engramia</strong> {days_since_signup} days ago but haven't confirmed your email yet.</p>
      {_button_html(href=verify_url, label="Verify my email")}
      <p style="margin:16px 0 8px 0; color:{_TEXT_MUTED}; font-size:13px;">Or paste this link into your browser:</p>
      <p style="margin:0 0 24px 0; word-break:break-all;"><a href="{safe_url}" style="color:{_BRAND_ACCENT_DARK}; text-decoration:underline; font-size:13px;">{safe_url}</a></p>
      <p style="margin:0; color:{_TEXT_MUTED}; font-size:13px;">If you don't confirm within {days_until_delete} days, we'll delete the pending account.</p>
    """
    html = _email_layout(
        content_html=content,
        preheader=f"Finish setting up your Engramia account within {days_until_delete} days.",
    )
    return subject, text, html
