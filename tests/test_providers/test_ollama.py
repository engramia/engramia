# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.providers.ollama (subclass of OpenAIProvider)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Skip the entire module if openai SDK is not installed (Ollama reuses it).
pytest.importorskip("openai", reason="openai SDK required for Ollama provider")

from engramia.providers.ollama import (
    OllamaEmbeddings,
    OllamaProvider,
)


class TestOllamaProvider:
    def test_subclass_of_openai_provider(self) -> None:
        from engramia.providers.openai import OpenAIProvider

        assert issubclass(OllamaProvider, OpenAIProvider)

    def test_default_base_url_is_localhost_v1(self) -> None:
        p = OllamaProvider()
        assert p._base_url == "http://localhost:11434/v1"

    def test_default_api_key_is_placeholder(self) -> None:
        """Ollama doesn't enforce auth, but the openai SDK requires a
        non-empty Bearer header — we pass a placeholder."""
        p = OllamaProvider()
        assert p._api_key == "ollama"

    def test_default_timeout_is_5_minutes(self) -> None:
        """CPU inference can be slow on cold load — 5 min default."""
        p = OllamaProvider()
        assert p._timeout == 300.0

    def test_custom_base_url_propagates(self) -> None:
        p = OllamaProvider(base_url="http://192.168.1.10:11434/v1")
        assert p._base_url == "http://192.168.1.10:11434/v1"

    def test_default_model_is_llama33(self) -> None:
        p = OllamaProvider()
        assert p._model == "llama3.3"

    def test_call_uses_chat_completions(self) -> None:
        """Inherits OpenAIProvider.call(), so the underlying API call
        path is chat.completions.create against the configured base_url."""
        p = OllamaProvider(model="qwen2.5-coder")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))]
        )
        # Bypass the lazy property
        p._client_cache = mock_client
        result = p.call("hello")
        assert result == "ok"
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "qwen2.5-coder"


class TestOllamaEmbeddings:
    def test_subclass_of_openai_embeddings(self) -> None:
        from engramia.providers.openai import OpenAIEmbeddings

        assert issubclass(OllamaEmbeddings, OpenAIEmbeddings)

    def test_default_model_is_nomic_embed(self) -> None:
        e = OllamaEmbeddings()
        assert e._model == "nomic-embed-text"

    def test_default_base_url(self) -> None:
        e = OllamaEmbeddings()
        assert e._base_url == "http://localhost:11434/v1"


class TestOpenAIClientArgs:
    """Verify that the OpenAI client is constructed with the right
    api_key and base_url when those are passed through Ollama."""

    def test_openai_client_built_with_ollama_base_url(self) -> None:
        with patch("openai.OpenAI") as mock_openai_cls:
            p = OllamaProvider(base_url="http://test:11434/v1")
            # Force lazy init
            _ = p._client
            mock_openai_cls.assert_called_once()
            kwargs = mock_openai_cls.call_args.kwargs
            assert kwargs["base_url"] == "http://test:11434/v1"
            assert kwargs["api_key"] == "ollama"
