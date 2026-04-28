# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Synchronous credential validation against the provider's API.

Used by ``POST /v1/credentials`` (decision A4: reject on validation failure)
and by the validate endpoint that the dashboard exposes for "test this key
without saving".

Each provider's lightest weight discovery endpoint is used:

- **OpenAI / OpenAI-compatible**: ``GET /v1/models`` — returns the model list.
- **Anthropic**: ``GET /v1/models`` — Anthropic ships an equivalent.
- **Google Gemini**: ``GET /v1beta/models`` (key in ``?key=`` query param).
- **Ollama**: ``GET /api/tags`` — local discovery, no auth.

A 200 response = key valid for at least listing models. A 401 / 403 = invalid.
Other failures (5xx, timeout, network error) are treated as inconclusive —
the API still rejects the create request (per A4) but the error message
distinguishes "auth failed" from "provider unreachable".

Decision A3: 5-second timeout. Decision A4: reject on auth failure rather
than store with status=invalid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from engramia.credentials.models import ProviderType

_log = logging.getLogger(__name__)

_VALIDATION_TIMEOUT_S: Final[float] = 5.0  # decision A3
_OPENAI_DEFAULT_BASE: Final[str] = "https://api.openai.com"
_ANTHROPIC_BASE: Final[str] = "https://api.anthropic.com"
_GEMINI_BASE: Final[str] = "https://generativelanguage.googleapis.com"
_OLLAMA_DEFAULT_BASE: Final[str] = "http://localhost:11434"


@dataclass
class ValidationResult:
    """Outcome of a single provider validation attempt.

    Attributes:
        success: True iff the provider returned a 2xx response — the key
            is usable for at least the model-list endpoint.
        error: Human-readable description for invalid / inconclusive cases.
            Safe to show to the tenant. Never contains the api_key.
        category: One of ``"ok" | "auth_failed" | "unreachable" | "config"``.
            ``auth_failed`` is the only category that justifies persisting
            with ``status='invalid'``; the others should be retried.
    """

    success: bool
    error: str | None
    category: str  # "ok" | "auth_failed" | "unreachable" | "config"


def _validate_openai_compat(api_key: str, base_url: str) -> ValidationResult:
    """Ping OpenAI-compatible /v1/models. Used for both OpenAI and Together/
    Groq/Fireworks/vLLM via the openai_compat provider."""
    url = f"{base_url.rstrip('/')}/v1/models"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_VALIDATION_TIMEOUT_S,
        )
    except httpx.TimeoutException:
        return ValidationResult(False, "Provider /models endpoint timed out", "unreachable")
    except httpx.HTTPError as exc:
        return ValidationResult(False, f"Provider unreachable: {exc.__class__.__name__}", "unreachable")
    if resp.status_code == 200:
        return ValidationResult(True, None, "ok")
    if resp.status_code in (401, 403):
        return ValidationResult(False, "Provider rejected the API key (401/403)", "auth_failed")
    return ValidationResult(
        False,
        f"Unexpected provider response: HTTP {resp.status_code}",
        "unreachable",
    )


def _validate_anthropic(api_key: str) -> ValidationResult:
    """Ping Anthropic /v1/models. Anthropic uses ``x-api-key`` header,
    not Bearer."""
    url = f"{_ANTHROPIC_BASE}/v1/models"
    try:
        resp = httpx.get(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=_VALIDATION_TIMEOUT_S,
        )
    except httpx.TimeoutException:
        return ValidationResult(False, "Anthropic /models endpoint timed out", "unreachable")
    except httpx.HTTPError as exc:
        return ValidationResult(False, f"Anthropic unreachable: {exc.__class__.__name__}", "unreachable")
    if resp.status_code == 200:
        return ValidationResult(True, None, "ok")
    if resp.status_code in (401, 403):
        return ValidationResult(False, "Anthropic rejected the API key (401/403)", "auth_failed")
    return ValidationResult(
        False,
        f"Unexpected Anthropic response: HTTP {resp.status_code}",
        "unreachable",
    )


def _validate_gemini(api_key: str) -> ValidationResult:
    """Ping Gemini ``/v1beta/models?key=...``. Gemini auth is by query
    parameter, not header — the URL itself contains the secret. We do not
    log the URL, only the result."""
    url = f"{_GEMINI_BASE}/v1beta/models?key={api_key}"
    try:
        resp = httpx.get(url, timeout=_VALIDATION_TIMEOUT_S)
    except httpx.TimeoutException:
        return ValidationResult(False, "Gemini /models endpoint timed out", "unreachable")
    except httpx.HTTPError as exc:
        return ValidationResult(False, f"Gemini unreachable: {exc.__class__.__name__}", "unreachable")
    if resp.status_code == 200:
        return ValidationResult(True, None, "ok")
    # Gemini returns 400 with INVALID_ARGUMENT for bad keys, not 401.
    if resp.status_code in (400, 401, 403):
        return ValidationResult(False, "Gemini rejected the API key", "auth_failed")
    return ValidationResult(
        False,
        f"Unexpected Gemini response: HTTP {resp.status_code}",
        "unreachable",
    )


def _validate_ollama(base_url: str) -> ValidationResult:
    """Ping Ollama /api/tags. Ollama is on-prem, has no real auth — we
    only check that the server responds."""
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return ValidationResult(False, "base_url must be a full URL", "config")
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        resp = httpx.get(url, timeout=_VALIDATION_TIMEOUT_S)
    except httpx.HTTPError as exc:
        return ValidationResult(
            False,
            f"Ollama unreachable at {parsed.netloc}: {exc.__class__.__name__}",
            "unreachable",
        )
    if resp.status_code == 200:
        return ValidationResult(True, None, "ok")
    return ValidationResult(
        False,
        f"Ollama responded HTTP {resp.status_code} at {parsed.netloc}",
        "unreachable",
    )


def validate(
    provider: ProviderType,
    api_key: str,
    *,
    base_url: str | None = None,
) -> ValidationResult:
    """Dispatch credential validation to the right provider implementation.

    Args:
        provider: One of the supported provider IDs.
        api_key: Plaintext key. NEVER logged. Caller must not echo this in
            error messages.
        base_url: Required for ``ollama`` and ``openai_compat``. Optional
            override for ``openai`` (e.g. Azure OpenAI).

    Returns:
        :class:`ValidationResult`. The route handler converts the category
        to an HTTP status: ``ok`` → 201 (persist), ``auth_failed`` /
        ``unreachable`` / ``config`` → 400 with the error message.
    """
    if provider == "openai":
        return _validate_openai_compat(api_key, base_url or _OPENAI_DEFAULT_BASE)
    if provider == "openai_compat":
        if not base_url:
            return ValidationResult(False, "base_url is required for openai_compat provider", "config")
        return _validate_openai_compat(api_key, base_url)
    if provider == "anthropic":
        return _validate_anthropic(api_key)
    if provider == "gemini":
        return _validate_gemini(api_key)
    if provider == "ollama":
        return _validate_ollama(base_url or _OLLAMA_DEFAULT_BASE)
    return ValidationResult(False, f"Unknown provider: {provider}", "config")
