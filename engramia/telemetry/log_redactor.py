# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pattern-based log redactor for LLM provider API keys and bearer tokens.

A defence-in-depth layer beneath the discipline of "do not log secrets". Even
with code review and pre-commit hooks, a stack trace from inside an LLM SDK
call can echo the ``Authorization`` header, or a debug print of a tenant's
credential payload could slip through. This module installs a ``logging.Filter``
that scans every log record's rendered message for known secret patterns and
replaces them with a tagged placeholder before the formatter writes them out.

Patterns covered:
    - Anthropic API keys      (sk-ant-…)
    - OpenAI API keys         (sk-…, sk-proj-…, sk-svcacct-…)
    - Google AI Studio keys   (AIza…)
    - Engramia API keys       (engramia_sk_…)
    - JWT tokens              (eyJ….….…)
    - Authorization: Bearer … (catch-all for headers in tracebacks)

Anthropic precedes OpenAI in the pattern list because both start with ``sk-``;
the more specific Anthropic pattern wins via earlier match.

Configuration:
    ``ENGRAMIA_LOG_REDACTION``    true | false  (default: true)

Caveats:
    - Operates on the rendered message and ``args``. Exception tracebacks
      formatted by the standard library AFTER the filter runs are not
      redacted by this module — keep the discipline of never f-stringing
      a credential into log output. Future work: subclass the formatter
      to redact ``exc_text`` as well.
    - Patterns are conservative to avoid false positives on UUIDs, git
      SHAs, or random IDs. They will NOT catch tokens that don't match
      a known prefix.
"""

from __future__ import annotations

import logging
import os
import re
from re import Pattern
from typing import Final

# Ordering matters: more specific patterns first.
# Each entry is (compiled_regex, replacement). Anthropic's "sk-ant-" must come
# before the broader OpenAI "sk-" pattern so it wins the match.
_PATTERNS: Final[list[tuple[Pattern[str], str]]] = [
    # Anthropic — sk-ant-api03-..., sk-ant-...
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "[REDACTED:anthropic_key]"),
    # OpenAI — sk-..., sk-proj-..., sk-svcacct-...
    # Length floor of 20 chars (post-prefix) keeps short legitimate
    # strings (e.g. "sk-yes-no") from triggering false positives.
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED:openai_key]"),
    # Google AI Studio — AIzaSy...
    # Exactly 39 chars after "AIza" per Google's documented format.
    (re.compile(r"AIza[A-Za-z0-9_\-]{35}"), "[REDACTED:google_ai_key]"),
    # Engramia API keys — engramia_sk_<url-safe base64, ≥20 chars>
    (re.compile(r"engramia_sk_[A-Za-z0-9_\-]{20,}"), "[REDACTED:engramia_key]"),
    # Authorization headers — preserve the "Authorization: Bearer " prefix so
    # operators can still see *that* a header was being logged, just not the
    # token. Using a capture group keeps the prefix intact in the replacement.
    (
        re.compile(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9_\-\.=]{16,}"),
        r"\1[REDACTED:bearer]",
    ),
    # JWT tokens — three base64url segments separated by dots. The "eyJ"
    # prefix is the base64-encoding of "{\"" (start of the JOSE header)
    # and is unique enough to avoid colliding with normal text.
    (
        re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        "[REDACTED:jwt]",
    ),
]

_REDACTION_ENV: Final[str] = "ENGRAMIA_LOG_REDACTION"


def redact(text: str) -> str:
    """Apply all redaction patterns to a string.

    Args:
        text: Raw log message — possibly containing secrets.

    Returns:
        The same text with any matched secret replaced by a tagged placeholder.
        Returns the input unchanged if no pattern matches.
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """logging.Filter that strips known secret patterns from each record.

    Operates on the *rendered* message (``record.getMessage()``) so that
    pattern matches catch values supplied via ``%`` formatting args. The
    rendered, redacted message is written back to ``record.msg`` and
    ``record.args`` is cleared to prevent double-formatting when the
    formatter runs.

    Filter never returns False — every record is allowed through. The only
    side-effect is in-place redaction.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            # If the record is malformed (mismatched %-args), let the
            # formatter raise its own diagnostic later — don't block emit.
            return True
        redacted = redact(rendered)
        if redacted != rendered:
            # Avoid losing information from extra-level args; we render the
            # full message ourselves and clear args so the formatter does not
            # re-substitute (which would raise on '%' marks introduced by the
            # placeholder text, and would also re-expose the original args).
            record.msg = redacted
            record.args = ()
        return True


def is_enabled() -> bool:
    """Return True if log redaction should be active for this process.

    Defaults to enabled. Set ``ENGRAMIA_LOG_REDACTION=false`` to disable —
    only useful in tests that need to assert on raw log output.
    """
    return os.environ.get(_REDACTION_ENV, "true").lower() not in {"false", "0", "no"}


def install_redaction_filter(logger: logging.Logger | None = None) -> RedactingFilter | None:
    """Attach a :class:`RedactingFilter` to the given logger (default: root).

    Idempotent — calling twice does not double-install. Returns the filter
    instance for inspection or removal in tests; returns None if redaction
    is disabled via env var.

    Args:
        logger: Logger to install on. Defaults to the root logger so that
            every module that calls ``logging.getLogger(__name__)`` inherits
            the filter through propagation.

    Returns:
        The installed filter, or None if redaction is disabled.
    """
    if not is_enabled():
        return None
    target = logger or logging.getLogger()
    # Idempotency: do not install twice
    for existing in target.filters:
        if isinstance(existing, RedactingFilter):
            return existing
    redactor = RedactingFilter()
    target.addFilter(redactor)
    return redactor
