# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.credentials.validator.

Mocks the outbound httpx call so the test suite stays hermetic. Tests
cover:
- Per-provider dispatch (openai, anthropic, gemini, ollama, openai_compat)
- Result categories: ok / auth_failed / unreachable / config
- Timeout and network error mapping to ``unreachable``
- 401/403 mapping to ``auth_failed``
- Provider-specific quirks (Anthropic x-api-key, Gemini ?key= query, Ollama
  no-auth on /api/tags)
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from engramia.credentials.validator import ValidationResult, validate


def _mock_response(status_code: int, body: str = "{}") -> httpx.Response:
    """Build an httpx.Response with the given status code."""
    return httpx.Response(status_code=status_code, content=body.encode())


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class TestOpenAI:
    def test_200_returns_ok(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            result = validate("openai", "sk-test-1234567890ABCDEF")
        assert isinstance(result, ValidationResult)
        assert result.success is True
        assert result.category == "ok"
        # Verify default base URL was used
        call_args = mock.call_args
        assert "api.openai.com" in call_args[0][0]

    def test_401_returns_auth_failed(self) -> None:
        with patch("httpx.get", return_value=_mock_response(401)):
            result = validate("openai", "sk-bad-key")
        assert result.success is False
        assert result.category == "auth_failed"
        assert "401" in (result.error or "")

    def test_403_returns_auth_failed(self) -> None:
        with patch("httpx.get", return_value=_mock_response(403)):
            result = validate("openai", "sk-bad-key")
        assert result.category == "auth_failed"

    def test_500_returns_unreachable(self) -> None:
        with patch("httpx.get", return_value=_mock_response(500)):
            result = validate("openai", "sk-key")
        assert result.success is False
        assert result.category == "unreachable"

    def test_timeout_returns_unreachable(self) -> None:
        with patch("httpx.get", side_effect=httpx.TimeoutException("slow")):
            result = validate("openai", "sk-key")
        assert result.category == "unreachable"
        assert "timed out" in (result.error or "")

    def test_network_error_returns_unreachable(self) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("dns fail")):
            result = validate("openai", "sk-key")
        assert result.category == "unreachable"

    def test_uses_bearer_auth_header(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            validate("openai", "sk-test-bearer")
        headers = mock.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test-bearer"

    def test_custom_base_url_routes_there(self) -> None:
        """OpenAI provider may override base URL for Azure OpenAI etc."""
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            validate("openai", "sk-test", base_url="https://my-azure.openai.azure.com")
        url = mock.call_args[0][0]
        assert "my-azure.openai.azure.com" in url


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class TestAnthropic:
    def test_200_returns_ok(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            result = validate("anthropic", "sk-ant-test-1234567890")
        assert result.success is True
        # Verify Anthropic uses x-api-key header, not Bearer
        headers = mock.call_args.kwargs["headers"]
        assert headers["x-api-key"] == "sk-ant-test-1234567890"
        assert "Authorization" not in headers
        assert headers["anthropic-version"] == "2023-06-01"

    def test_401_returns_auth_failed(self) -> None:
        with patch("httpx.get", return_value=_mock_response(401)):
            result = validate("anthropic", "sk-ant-bad")
        assert result.category == "auth_failed"

    def test_pings_anthropic_models_endpoint(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            validate("anthropic", "sk-ant-test")
        url = mock.call_args[0][0]
        assert url == "https://api.anthropic.com/v1/models"


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class TestGemini:
    def test_200_returns_ok(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200)):
            result = validate("gemini", "AIzaTestKey1234567890")
        assert result.success is True

    def test_400_returns_auth_failed(self) -> None:
        """Gemini returns 400 INVALID_ARGUMENT for bad keys, not 401."""
        with patch("httpx.get", return_value=_mock_response(400)):
            result = validate("gemini", "AIza-bad")
        assert result.category == "auth_failed"

    def test_uses_query_param_for_auth(self) -> None:
        """Gemini auth is by ?key= query param."""
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            validate("gemini", "AIzaSecret123")
        url = mock.call_args[0][0]
        assert "key=AIzaSecret123" in url
        # No Authorization header
        headers = mock.call_args.kwargs.get("headers", {})
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class TestOllama:
    """Validator dispatch + URL handling for Ollama. The deeper coverage
    (default_model pulled-check, model list surfacing, model_missing
    category) lives in tests/test_credentials/test_validator_ollama.py
    — added in Phase 6.6 #4 alongside the native /api/tags integration.
    """

    @pytest.fixture(autouse=True)
    def _clear_ollama_cache(self):
        from engramia.providers._ollama_native import get_default_cache

        get_default_cache().clear()
        yield
        get_default_cache().clear()

    def test_200_returns_ok(self) -> None:
        from engramia.providers._ollama_native import OllamaModel

        with patch(
            "engramia.providers._ollama_native.list_models",
            return_value=[OllamaModel(name="llama3.3:latest")],
        ):
            result = validate("ollama", "ignored", base_url="http://localhost:11434")
        assert result.success is True
        assert result.category == "ok"

    def test_uses_default_base_url_when_none(self) -> None:
        from engramia.providers._ollama_native import OllamaModel

        with patch(
            "engramia.providers._ollama_native.list_models",
            return_value=[OllamaModel(name="llama3.3:latest")],
        ) as mock:
            validate("ollama", "ignored")
        # First positional arg is the base URL; default is localhost:11434
        url_arg = mock.call_args[0][0]
        assert "localhost:11434" in url_arg

    def test_unreachable_when_no_response(self) -> None:
        with patch(
            "engramia.providers._ollama_native.list_models",
            side_effect=httpx.ConnectError("refused"),
        ):
            result = validate("ollama", "ignored", base_url="http://10.0.0.99:11434")
        assert result.category == "unreachable"
        assert "10.0.0.99" in (result.error or "")  # netloc surfaced

    def test_invalid_url_returns_config_error(self) -> None:
        result = validate("ollama", "ignored", base_url="not-a-url")
        assert result.category == "config"


# ---------------------------------------------------------------------------
# OpenAI-compatible
# ---------------------------------------------------------------------------


class TestOpenAICompat:
    def test_requires_base_url(self) -> None:
        result = validate("openai_compat", "sk-test")
        assert result.success is False
        assert result.category == "config"
        assert "base_url" in (result.error or "")

    def test_with_base_url_works(self) -> None:
        with patch("httpx.get", return_value=_mock_response(200)) as mock:
            result = validate(
                "openai_compat",
                "sk-test",
                base_url="https://api.together.xyz",
            )
        assert result.success is True
        url = mock.call_args[0][0]
        assert "api.together.xyz" in url


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------


class TestUnknownProvider:
    def test_unknown_returns_config_error(self) -> None:
        result = validate("xai", "sk-grok")  # type: ignore[arg-type]
        assert result.success is False
        assert result.category == "config"
        assert "Unknown provider" in (result.error or "")


# ---------------------------------------------------------------------------
# Error message hygiene
# ---------------------------------------------------------------------------


class TestErrorMessageHygiene:
    def test_error_does_not_echo_api_key(self) -> None:
        """Validation error messages must never echo the api_key — even
        on auth_failed, the message describes "the key was rejected" not
        "key sk-...abcd was rejected"."""
        with patch("httpx.get", return_value=_mock_response(401)):
            result = validate("openai", "sk-LEAK-DETECTOR-1234567890")
        assert "sk-LEAK-DETECTOR" not in (result.error or "")

    def test_gemini_error_does_not_echo_key_from_url(self) -> None:
        """Gemini puts the key in the URL — error message must not include it."""
        with patch("httpx.get", return_value=_mock_response(400)):
            result = validate("gemini", "AIza-LEAK-DETECTOR-1234567890")
        assert "LEAK-DETECTOR" not in (result.error or "")
