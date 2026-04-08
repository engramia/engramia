# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""PII and secrets redaction pipeline (Phase 5.6).

Pre-storage hook that scans and masks sensitive content in pattern data.
Regex-only for predictability and speed — no LLM calls.

Usage::

    pipeline = RedactionPipeline.default()
    clean_design, findings = pipeline.process(design_dict)
    if findings:
        # store clean_design, mark pattern as redacted=True
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Finding — a single detected PII/secret occurrence
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single PII or secret occurrence detected in pattern data.

    Args:
        field: Which field of the pattern data was scanned (e.g. ``"code"``).
        kind: Detection category (e.g. ``"email"``, ``"api_key"``).
        count: Number of occurrences found in that field.
    """

    field: str
    kind: str
    count: int = 1


# ---------------------------------------------------------------------------
# RedactionHook ABC
# ---------------------------------------------------------------------------


class RedactionHook(ABC):
    """Base class for a single redaction pass."""

    @abstractmethod
    def scan(self, text: str) -> list[Finding]:
        """Detect PII/secrets in text. Returns findings WITHOUT the actual values."""

    @abstractmethod
    def redact(self, text: str) -> str:
        """Return text with all detected items replaced by placeholders."""


# ---------------------------------------------------------------------------
# RegexRedactor — structural patterns (emails, IPs, JWTs, ...)
# ---------------------------------------------------------------------------

# Pattern → (name, replacement)
_REGEX_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "email",
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I),
        "[REDACTED_EMAIL]",
    ),
    (
        "ipv4",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "[REDACTED_IP]",
    ),
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"),
        "[REDACTED_JWT]",
    ),
    (
        "openai_key",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        "[REDACTED_OPENAI_KEY]",
    ),
    (
        "aws_access_key",
        re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        "[REDACTED_AWS_KEY]",
    ),
    (
        "github_token",
        re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        "phone",
        # International: +CC or 00CC followed by digit groups (e.g. +1-800-555-0123,
        # +44 7700 900123, +420 123 456 789). Domestic: (NXX) NXX-XXXX.
        # Each group must have ≥2 digits to suppress version/math false-positives.
        re.compile(
            r"""
            (?<!\d)          # not preceded by a digit
            (?:
                (?:\+|00)[1-9]\d{0,3}   # country code: +1, +44, +420, 001 …
                (?:[\s\-.]?\d{2,}){2,5} # 2-5 digit groups, each ≥2 digits
            |
                \(\d{2,4}\)[\s\-.]?\d{3,4}[\s\-.]?\d{3,6}  # (NXX) NXX-XXXX
            )
            (?!\d)           # not followed by a digit
            """,
            re.VERBOSE,
        ),
        "[REDACTED_PHONE]",
    ),
    (
        "credit_card",
        # Structural card patterns (Luhn-aware first-digit ranges + correct length).
        # Amex: 4-6-5 digits (15 total), starts with 34/37.
        # Visa: 16 digits, starts with 4.
        # Mastercard: 16 digits, starts with 51-55 or 2221-2720 range.
        # Discover: 16 digits, starts with 6011 or 65xx.
        # Separators between groups: space, dash, or none.
        re.compile(
            r"""
            (?<!\d)   # not preceded by a digit
            (?:
                3[47]\d{2}[\s\-]?\d{6}[\s\-]?\d{5}              # Amex 4-6-5
              | 4\d{3}(?:[\s\-]?\d{4}){3}                        # Visa 4×4
              | (?:5[1-5]\d{2}|2[2-7]\d{2})(?:[\s\-]?\d{4}){3}  # Mastercard 4×4
              | (?:6011|65\d{2})(?:[\s\-]?\d{4}){3}              # Discover 4×4
            )
            (?!\d)    # not followed by a digit
            """,
            re.VERBOSE,
        ),
        "[REDACTED_CARD]",
    ),
    (
        "hex_secret",
        # 32-64 hex chars as standalone token (likely an API key / secret)
        re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,64}(?![A-Za-z0-9])"),
        "[REDACTED_SECRET]",
    ),
]


class RegexRedactor(RedactionHook):
    """Detects and masks structural PII/secret patterns via regex."""

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for name, pattern, _ in _REGEX_RULES:
            matches = pattern.findall(text)
            if matches:
                findings.append(Finding(field="", kind=name, count=len(matches)))
        return findings

    def redact(self, text: str) -> str:
        for _, pattern, replacement in _REGEX_RULES:
            text = pattern.sub(replacement, text)
        return text


# ---------------------------------------------------------------------------
# SecretPatternRedactor — keyword-prefixed assignment patterns
# ---------------------------------------------------------------------------

_SECRET_KEYWORDS = [
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "auth_key",
    "access_key",
    "private_key",
    "client_secret",
    "bearer",
]

# Matches key = "value", key: "value", key = 'value', KEY="value", etc.
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(?:" + "|".join(re.escape(k) for k in _SECRET_KEYWORDS) + r""")[\s]*(?:=|:)[\s]*["']?([^"'\s,;>]{6,})["']?""",
)


class SecretPatternRedactor(RedactionHook):
    """Detects and masks keyword-prefixed credential assignments."""

    def scan(self, text: str) -> list[Finding]:
        matches = _SECRET_ASSIGNMENT_PATTERN.findall(text)
        if matches:
            return [Finding(field="", kind="credential_assignment", count=len(matches))]
        return []

    def redact(self, text: str) -> str:
        return _SECRET_ASSIGNMENT_PATTERN.sub(
            lambda m: m.group(0).replace(m.group(1), "[REDACTED]"),
            text,
        )


# ---------------------------------------------------------------------------
# RedactionPipeline — compose hooks, process pattern dicts
# ---------------------------------------------------------------------------

# Fields of pattern.design that should be scanned
_SCANNABLE_FIELDS = {"code", "output", "task"}


class RedactionPipeline:
    """Composable pipeline of RedactionHook instances.

    Processes all string values in a pattern design dict. Returns a cleaned
    copy of the dict and a list of findings (without actual PII values).

    Args:
        hooks: Ordered list of RedactionHook instances to apply.
    """

    def __init__(self, hooks: list[RedactionHook]) -> None:
        self._hooks = hooks

    @classmethod
    def default(cls) -> RedactionPipeline:
        """Return a pipeline with all built-in hooks enabled."""
        return cls(hooks=[RegexRedactor(), SecretPatternRedactor()])

    @classmethod
    def empty(cls) -> RedactionPipeline:
        """Return a no-op pipeline (redaction disabled)."""
        return cls(hooks=[])

    def process(
        self, data: dict[str, Any], extra_fields: dict[str, str] | None = None
    ) -> tuple[dict[str, Any], list[Finding]]:
        """Scan and redact a pattern design dict.

        Args:
            data: Pattern design dict (e.g. ``{"code": "...", "output": "..."}``)
            extra_fields: Additional top-level fields to scan (e.g. ``{"task": "..."}``)

        Returns:
            Tuple of ``(redacted_data, findings)``. ``redacted_data`` is a
            shallow copy with string values replaced. ``findings`` lists all
            detected items by field and kind (no actual values stored).
        """
        if not self._hooks:
            return data, []

        all_findings: list[Finding] = []
        clean: dict[str, Any] = {}

        # Merge extra fields into scan target
        scan_target: dict[str, Any] = {**data}
        if extra_fields:
            scan_target.update(extra_fields)

        for field_name, value in scan_target.items():
            if not isinstance(value, str) or not value:
                clean[field_name] = value
                continue

            field_findings: list[Finding] = []
            cleaned_value = value

            for hook in self._hooks:
                hook_findings = hook.scan(cleaned_value)
                for f in hook_findings:
                    f.field = field_name
                field_findings.extend(hook_findings)
                if hook_findings:
                    cleaned_value = hook.redact(cleaned_value)

            clean[field_name] = cleaned_value
            all_findings.extend(field_findings)

        if all_findings:
            _log.info(
                "Redaction: %d finding(s) in fields %s",
                len(all_findings),
                sorted({f.field for f in all_findings}),
            )

        return clean, all_findings
