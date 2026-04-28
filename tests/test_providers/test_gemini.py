# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Smoke tests for engramia.providers.gemini.

Skipped when the optional ``google-genai`` SDK is not installed (e.g.
on the default CI runner without the gemini extra). Real Gemini API
calls are mocked — these tests verify the provider construction
contract and that BYOK ``api_key`` is forwarded to the SDK.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Skip the entire module if the SDK is absent. The provider's ImportError
# guard handles this at runtime; tests should not crash CI.
google_genai = pytest.importorskip("google.genai", reason="google-genai SDK required")

from engramia.providers.gemini import GeminiEmbeddings, GeminiProvider  # noqa: E402


class TestGeminiProviderConstruction:
    def test_explicit_api_key_passed_to_client(self) -> None:
        with patch("google.genai.Client") as mock_client_cls:
            GeminiProvider(api_key="AIza-test-1234567890")
            mock_client_cls.assert_called_once_with(api_key="AIza-test-1234567890")

    def test_no_api_key_uses_env_default(self) -> None:
        """Backward compat: SDK reads GOOGLE_API_KEY when no explicit key."""
        with patch("google.genai.Client") as mock_client_cls:
            GeminiProvider()
            # genai.Client() called with no args → SDK uses env var
            mock_client_cls.assert_called_once_with()

    def test_default_model_is_gemini_25_flash(self) -> None:
        with patch("google.genai.Client"):
            p = GeminiProvider()
            assert p._model == "gemini-2.5-flash"

    def test_repr_does_not_leak_api_key(self) -> None:
        with patch("google.genai.Client"):
            p = GeminiProvider(api_key="AIza-LEAK-DETECTOR-1234567890")
        assert "AIza-LEAK" not in repr(p)


class TestGeminiProviderCall:
    def test_call_returns_response_text(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock(text="hello from gemini")
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            p = GeminiProvider(api_key="AIza-test")
            result = p.call("say hi")
        assert result == "hello from gemini"

    def test_call_joins_system_and_prompt(self) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = MagicMock(text="ok")

        with patch("google.genai.Client", return_value=mock_client):
            p = GeminiProvider(api_key="AIza-test")
            p.call("user prompt", system="be concise")

        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert "be concise" in contents
        assert "user prompt" in contents


class TestGeminiEmbeddings:
    def test_explicit_api_key_passed_to_client(self) -> None:
        with patch("google.genai.Client") as mock_client_cls:
            GeminiEmbeddings(api_key="AIza-emb-test")
            mock_client_cls.assert_called_once_with(api_key="AIza-emb-test")

    def test_default_model_is_gemini_embedding_001(self) -> None:
        with patch("google.genai.Client"):
            e = GeminiEmbeddings()
            assert e._model == "gemini-embedding-001"

    def test_embed_returns_vector(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock(embeddings=[MagicMock(values=[0.1, 0.2, 0.3])])
        mock_client.models.embed_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            e = GeminiEmbeddings(api_key="AIza-test")
            result = e.embed("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_batch_returns_list_of_vectors(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock(
            embeddings=[
                MagicMock(values=[0.1, 0.2]),
                MagicMock(values=[0.3, 0.4]),
            ]
        )
        mock_client.models.embed_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            e = GeminiEmbeddings(api_key="AIza-test")
            result = e.embed_batch(["a", "b"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    def test_embed_batch_empty_returns_empty(self) -> None:
        with patch("google.genai.Client"):
            e = GeminiEmbeddings(api_key="AIza-test")
            assert e.embed_batch([]) == []
