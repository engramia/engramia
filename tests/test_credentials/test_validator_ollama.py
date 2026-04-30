# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Phase 6.6 #4 — credential validator for Ollama via native /api/tags.

Three validation outcomes covered:

- **success** — server reachable, has models pulled, default_model
  matches one of them.
- **model_missing** — server reachable, has models, but the configured
  default_model isn't in the pulled set.
- **config (empty server)** — server reachable, no models pulled at all.
- **unreachable** — timeout, connect error, malformed base_url.

Plus the URL-suffix bug fix: the pre-#4 validator pinged
``{base_url}/api/tags`` and 404'd whenever the credential's base_url
carried the ``/v1`` suffix the openai SDK actually needs. The new
validator strips ``/v1`` via :func:`native_base_url`.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from engramia.credentials import validator
from engramia.credentials.validator import validate
from engramia.providers._ollama_native import OllamaModel


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the shared model-list cache so tests don't leak across files."""
    from engramia.providers._ollama_native import get_default_cache

    get_default_cache().clear()
    yield
    get_default_cache().clear()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestOllamaSuccess:
    def test_returns_ok_with_models_when_default_pulled(self):
        models = [
            OllamaModel(name="llama3.3:latest"),
            OllamaModel(name="qwen2.5:7b"),
        ]
        with (
            patch.object(validator, "_OLLAMA_DEFAULT_BASE", "http://localhost:11434"),
            patch("engramia.providers._ollama_native.list_models", return_value=models),
        ):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434/v1",
                default_model="llama3.3",
            )
        assert result.success is True
        assert result.category == "ok"
        assert result.error is None
        assert result.models_available == ["llama3.3:latest", "qwen2.5:7b"]

    def test_strips_v1_suffix_before_calling_native_api(self):
        """The pre-#4 bug: validator pinged base_url + /api/tags directly,
        which 404'd on the OpenAI-compat /v1 suffix. Verify the call
        site uses the native helper which normalises the URL."""
        models = [OllamaModel(name="llama3.3:latest")]
        captured_base = {}

        def _capture(base_url, **kwargs):
            captured_base["url"] = base_url
            return models

        with patch("engramia.providers._ollama_native.list_models", side_effect=_capture):
            validate(
                "ollama",
                "ollama",
                base_url="http://my-ollama.local:11434/v1",
                default_model="llama3.3",
            )

        # The validator passes the raw base_url through; the native
        # helper's native_base_url() does the strip. We assert the
        # validator did not pre-mangle it (the integration is what
        # matters — separate test in test_ollama_native covers the
        # strip itself).
        assert captured_base["url"] == "http://my-ollama.local:11434/v1"

    def test_no_default_model_means_no_pulled_check(self):
        """Tenants who omit default_model still pass when the server has
        any models pulled — they're saying "auto-detect later"."""
        models = [OllamaModel(name="llama3.3:latest")]
        with patch("engramia.providers._ollama_native.list_models", return_value=models):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434",
                default_model=None,
            )
        assert result.success is True
        assert result.category == "ok"


# ---------------------------------------------------------------------------
# Missing default_model
# ---------------------------------------------------------------------------


class TestModelMissing:
    def test_typo_in_default_model_returns_model_missing(self):
        models = [
            OllamaModel(name="llama3.3:latest"),
            OllamaModel(name="qwen2.5:7b"),
        ]
        with patch("engramia.providers._ollama_native.list_models", return_value=models):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434",
                default_model="llama3.4",  # typo
            )
        assert result.success is False
        assert result.category == "model_missing"
        assert "not pulled" in result.error
        assert "llama3.3:latest" in result.error  # available list helps the user
        # Available list still surfaced for the dashboard
        assert result.models_available == ["llama3.3:latest", "qwen2.5:7b"]

    def test_error_truncates_long_pulled_lists(self):
        # A server with 20 models shouldn't blow the error message into
        # an unreadable wall — we cap the listed names at 8.
        models = [OllamaModel(name=f"model-{i}:latest") for i in range(20)]
        with patch("engramia.providers._ollama_native.list_models", return_value=models):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434",
                default_model="missing-one",
            )
        assert "..." in result.error
        # First few names appear, the rest collapsed into "..."
        assert "model-0:latest" in result.error
        assert "model-19:latest" not in result.error


# ---------------------------------------------------------------------------
# Server has no models pulled
# ---------------------------------------------------------------------------


class TestEmptyServer:
    def test_zero_models_returns_config_error(self):
        """A reachable Ollama server with no models pulled is technically
        up but unusable. The config category tells the route handler to
        reject the credential at create time."""
        with patch("engramia.providers._ollama_native.list_models", return_value=[]):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434",
                default_model="llama3.3",
            )
        assert result.success is False
        assert result.category == "config"
        assert "no models pulled" in result.error.lower()
        assert "ollama pull" in result.error.lower()
        assert result.models_available == []


# ---------------------------------------------------------------------------
# Server unreachable
# ---------------------------------------------------------------------------


class TestUnreachable:
    def test_timeout_returns_unreachable(self):
        with patch(
            "engramia.providers._ollama_native.list_models",
            side_effect=httpx.TimeoutException("read timeout"),
        ):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434",
                default_model="llama3.3",
            )
        assert result.success is False
        assert result.category == "unreachable"
        assert "timed out" in result.error.lower()

    def test_connect_error_returns_unreachable(self):
        with patch(
            "engramia.providers._ollama_native.list_models",
            side_effect=httpx.ConnectError("refused"),
        ):
            result = validate(
                "ollama",
                "ollama",
                base_url="http://localhost:11434",
                default_model="llama3.3",
            )
        assert result.success is False
        assert result.category == "unreachable"
        assert "ConnectError" in result.error

    def test_malformed_url_returns_config(self):
        result = validate(
            "ollama",
            "ollama",
            base_url="not-a-url",
            default_model="llama3.3",
        )
        assert result.success is False
        assert result.category == "config"
        assert "full URL" in result.error
