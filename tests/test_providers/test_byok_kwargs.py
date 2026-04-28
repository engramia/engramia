# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the BYOK constructor arguments (api_key, base_url) added to
OpenAI and Anthropic providers in Phase 6.6.

The refactor must preserve backward compatibility: callers who omit
``api_key`` get the same env-var fallback behaviour as before, while
callers who pass an explicit key (the cloud factory) get a per-tenant
client instance.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# Skip when SDKs are absent — the providers' module-level ImportError
# guards on instantiation, but we want the test suite to work either way.
openai_module = pytest.importorskip("openai", reason="openai SDK required")
anthropic_module = pytest.importorskip("anthropic", reason="anthropic SDK required")


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class TestOpenAIProviderApiKeyKwarg:
    def test_no_api_key_uses_env_default(self) -> None:
        """Backward compat: OpenAIProvider() without api_key constructs
        the SDK client without explicit auth, so the SDK reads
        OPENAI_API_KEY from the environment."""
        from engramia.providers.openai import OpenAIProvider

        with patch("openai.OpenAI") as mock_cls:
            p = OpenAIProvider()
            _ = p._client
            kwargs = mock_cls.call_args.kwargs
            assert "api_key" not in kwargs

    def test_explicit_api_key_passed_to_sdk(self) -> None:
        from engramia.providers.openai import OpenAIProvider

        with patch("openai.OpenAI") as mock_cls:
            p = OpenAIProvider(api_key="sk-explicit-1234567890")
            _ = p._client
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["api_key"] == "sk-explicit-1234567890"

    def test_explicit_base_url_passed_to_sdk(self) -> None:
        from engramia.providers.openai import OpenAIProvider

        with patch("openai.OpenAI") as mock_cls:
            p = OpenAIProvider(base_url="https://my-azure.openai.azure.com")
            _ = p._client
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["base_url"] == "https://my-azure.openai.azure.com"

    def test_repr_does_not_leak_api_key(self) -> None:
        """Defence-in-depth: provider instances must not echo the api_key
        in their default repr (logging, error tracebacks)."""
        from engramia.providers.openai import OpenAIProvider

        p = OpenAIProvider(api_key="sk-LEAK-DETECTOR-1234567890")
        # The default object repr contains memory id only, not attribute values
        assert "sk-LEAK" not in repr(p)


class TestOpenAIEmbeddingsApiKeyKwarg:
    def test_explicit_api_key_passed_to_sdk(self) -> None:
        from engramia.providers.openai import OpenAIEmbeddings

        with patch("openai.OpenAI") as mock_cls:
            e = OpenAIEmbeddings(api_key="sk-emb-1234567890")
            _ = e._client
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["api_key"] == "sk-emb-1234567890"

    def test_no_api_key_no_explicit_sdk_arg(self) -> None:
        from engramia.providers.openai import OpenAIEmbeddings

        with patch("openai.OpenAI") as mock_cls:
            e = OpenAIEmbeddings()
            _ = e._client
            kwargs = mock_cls.call_args.kwargs
            assert "api_key" not in kwargs


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class TestAnthropicProviderApiKeyKwarg:
    def test_no_api_key_uses_env_default(self) -> None:
        """Backward compat path."""
        from engramia.providers.anthropic import AnthropicProvider

        with patch("anthropic.Anthropic") as mock_cls:
            AnthropicProvider()
            kwargs = mock_cls.call_args.kwargs
            assert "api_key" not in kwargs

    def test_explicit_api_key_passed_to_sdk(self) -> None:
        from engramia.providers.anthropic import AnthropicProvider

        with patch("anthropic.Anthropic") as mock_cls:
            AnthropicProvider(api_key="sk-ant-explicit-1234567890")
            kwargs = mock_cls.call_args.kwargs
            assert kwargs["api_key"] == "sk-ant-explicit-1234567890"

    def test_repr_does_not_leak_api_key(self) -> None:
        from engramia.providers.anthropic import AnthropicProvider

        with patch("anthropic.Anthropic"):
            p = AnthropicProvider(api_key="sk-ant-LEAK-DETECTOR-1234567890")
        assert "sk-ant-LEAK" not in repr(p)
