# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.telemetry.log_redactor."""

from __future__ import annotations

import logging

import pytest

from engramia.telemetry import log_redactor
from engramia.telemetry.log_redactor import (
    RedactingFilter,
    install_redaction_filter,
    is_enabled,
    redact,
)

# ---------------------------------------------------------------------------
# Per-pattern coverage
# ---------------------------------------------------------------------------


def test_redacts_anthropic_key() -> None:
    msg = "Failed: sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF"
    out = redact(msg)
    assert "sk-ant-" not in out
    assert "[REDACTED:anthropic_key]" in out


def test_redacts_openai_key() -> None:
    msg = "key=sk-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF in env"
    out = redact(msg)
    assert "sk-AbCdEfGh" not in out
    assert "[REDACTED:openai_key]" in out


def test_redacts_openai_project_key() -> None:
    msg = "Authorization=sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF"
    out = redact(msg)
    assert "sk-proj-Ab" not in out
    assert "[REDACTED:openai_key]" in out


def test_redacts_google_ai_key() -> None:
    # Google AI keys: "AIza" + 35 chars
    msg = "key=AIzaSy" + "X" * 33  # AIza + 'Sy' + 33 chars = 39 total post-prefix
    out = redact(msg)
    assert "AIzaSy" not in out
    assert "[REDACTED:google_ai_key]" in out


def test_redacts_engramia_api_key() -> None:
    msg = "Authorization: engramia_sk_aB3dEf7HiJkLmNoPqRsT_uVwXyZ12345678"
    out = redact(msg)
    assert "engramia_sk_aB3" not in out
    assert "[REDACTED:engramia_key]" in out


def test_redacts_authorization_bearer() -> None:
    msg = "headers: Authorization: Bearer abcDEF123456GHIJK789opaque"
    out = redact(msg)
    # Prefix preserved so operators see THAT a token was logged
    assert "Authorization: Bearer" in out
    assert "abcDEF123456" not in out
    assert "[REDACTED:bearer]" in out


def test_redacts_jwt() -> None:
    msg = "session=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxw_-RgEMpUuNb"
    out = redact(msg)
    assert "eyJhbGci" not in out
    assert "[REDACTED:jwt]" in out


# ---------------------------------------------------------------------------
# Pattern priority (Anthropic before generic OpenAI)
# ---------------------------------------------------------------------------


def test_anthropic_takes_priority_over_openai_pattern() -> None:
    """sk-ant-... must redact as anthropic_key, not openai_key, even though
    both patterns share the sk- prefix. Anthropic appears earlier in the
    pattern list so it wins."""
    msg = "key=sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF"
    out = redact(msg)
    assert "[REDACTED:anthropic_key]" in out
    assert "[REDACTED:openai_key]" not in out


# ---------------------------------------------------------------------------
# False positives (expected non-redaction)
# ---------------------------------------------------------------------------


def test_does_not_redact_short_sk_prefix() -> None:
    """The 20-char floor prevents legitimate short tokens from triggering."""
    msg = "Status: sk-ok"
    assert redact(msg) == msg


def test_does_not_redact_uuid() -> None:
    msg = "request_id=550e8400-e29b-41d4-a716-446655440000"
    assert redact(msg) == msg


def test_does_not_redact_git_sha() -> None:
    msg = "commit b4ead7a3f9c8e2d1a0b9c8d7e6f5a4b3c2d1e0f9"
    assert redact(msg) == msg


def test_does_not_redact_normal_text() -> None:
    msg = "User logged in successfully from 192.168.1.1"
    assert redact(msg) == msg


# ---------------------------------------------------------------------------
# Multiple secrets in one message
# ---------------------------------------------------------------------------


def test_redacts_multiple_secrets_in_one_message() -> None:
    msg = (
        "openai=sk-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF "
        "anthropic=sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF "
        "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.AbCdEf"
    )
    out = redact(msg)
    assert "[REDACTED:openai_key]" in out
    assert "[REDACTED:anthropic_key]" in out
    assert "[REDACTED:jwt]" in out
    # No leakage
    assert "sk-AbCdEfGh" not in out
    assert "sk-ant-api" not in out
    assert "eyJhbGci" not in out


# ---------------------------------------------------------------------------
# Logging filter integration
# ---------------------------------------------------------------------------


def _make_record(msg: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_filter_redacts_record_message() -> None:
    f = RedactingFilter()
    record = _make_record("api_key=sk-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF")
    assert f.filter(record) is True
    assert "[REDACTED:openai_key]" in record.getMessage()
    assert "sk-AbCdEfGh" not in record.getMessage()


def test_filter_redacts_after_args_substitution() -> None:
    """Secrets supplied via %-args MUST be redacted after substitution.
    This is the common case where developer accidentally logs a secret
    via logger.info("token=%s", api_key)."""
    f = RedactingFilter()
    record = _make_record("token=%s", args=("sk-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF",))
    f.filter(record)
    assert "[REDACTED:openai_key]" in record.getMessage()
    # args must be cleared so formatter does not re-substitute
    assert record.args == ()


def test_filter_passes_through_clean_messages() -> None:
    f = RedactingFilter()
    record = _make_record("User logged in")
    assert f.filter(record) is True
    assert record.getMessage() == "User logged in"


def test_filter_does_not_block_records() -> None:
    f = RedactingFilter()
    record = _make_record("anything")
    assert f.filter(record) is True


def test_filter_handles_malformed_args_gracefully() -> None:
    """%-args mismatch — filter must not crash, just pass through."""
    f = RedactingFilter()
    record = _make_record("token=%s and %s", args=("only-one",))
    # Filter returns True (allow) without raising
    assert f.filter(record) is True


# ---------------------------------------------------------------------------
# install_redaction_filter
# ---------------------------------------------------------------------------


def test_install_filter_attaches_to_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGRAMIA_LOG_REDACTION", "true")
    root = logging.getLogger()
    initial_filters = len(root.filters)
    try:
        result = install_redaction_filter()
        assert result is not None
        assert isinstance(result, RedactingFilter)
        assert any(isinstance(f, RedactingFilter) for f in root.filters)
    finally:
        # Cleanup
        root.filters = root.filters[:initial_filters]


def test_install_filter_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGRAMIA_LOG_REDACTION", "true")
    root = logging.getLogger()
    initial_filters = len(root.filters)
    try:
        f1 = install_redaction_filter()
        f2 = install_redaction_filter()
        assert f1 is f2  # Same instance returned
        # Only one RedactingFilter on root
        assert sum(isinstance(f, RedactingFilter) for f in root.filters) == 1
    finally:
        root.filters = root.filters[:initial_filters]


def test_install_filter_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGRAMIA_LOG_REDACTION", "false")
    assert install_redaction_filter() is None


def test_install_filter_on_specific_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGRAMIA_LOG_REDACTION", "true")
    target = logging.getLogger("test.specific")
    target.filters = []
    try:
        result = install_redaction_filter(target)
        assert result is not None
        assert any(isinstance(f, RedactingFilter) for f in target.filters)
    finally:
        target.filters = []


# ---------------------------------------------------------------------------
# is_enabled env-var handling
# ---------------------------------------------------------------------------


def test_is_enabled_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENGRAMIA_LOG_REDACTION", raising=False)
    assert is_enabled() is True


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "No"])
def test_is_enabled_false_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ENGRAMIA_LOG_REDACTION", value)
    assert is_enabled() is False


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", ""])
def test_is_enabled_true_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("ENGRAMIA_LOG_REDACTION", value)
    assert is_enabled() is True


# ---------------------------------------------------------------------------
# End-to-end: caplog with filter installed
# ---------------------------------------------------------------------------


def test_caplog_sees_redacted_output(caplog: pytest.LogCaptureFixture) -> None:
    """Realistic developer-mistake scenario: someone logs a credential
    via %-args. The filter must intercept and the captured log entries
    must contain the placeholder, not the secret."""
    logger = logging.getLogger("test.redact_e2e")
    logger.addFilter(RedactingFilter())
    logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG, logger="test.redact_e2e"):
            logger.info("calling provider with %s", "sk-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDEF")
        assert any("[REDACTED:openai_key]" in r.getMessage() for r in caplog.records)
        assert all("sk-AbCdEfGh" not in r.getMessage() for r in caplog.records)
    finally:
        logger.filters = []


# ---------------------------------------------------------------------------
# Module-level reference check
# ---------------------------------------------------------------------------


def test_module_exports() -> None:
    """Sanity check that public symbols are reachable from the module."""
    assert log_redactor.redact is not None
    assert log_redactor.RedactingFilter is not None
    assert log_redactor.install_redaction_filter is not None
    assert log_redactor.is_enabled is not None
