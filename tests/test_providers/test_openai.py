# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for OpenAI providers (mocked — no API key required)."""

from unittest.mock import MagicMock, patch

import pytest

from engramia.providers.openai import OpenAIEmbeddings, OpenAIProvider


@pytest.fixture
def mock_openai(monkeypatch):
    """Patch openai.OpenAI so tests never call the real API."""
    mock_client = MagicMock()
    with patch("engramia.providers.openai.OpenAIProvider.__init__") as mock_init:
        mock_init.return_value = None
        yield mock_client


class TestOpenAIProvider:
    def _make_provider(self) -> OpenAIProvider:
        provider = OpenAIProvider.__new__(OpenAIProvider)
        provider._model = "gpt-4.1"
        provider._max_retries = 3
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="hello"))]
        )
        provider._client = mock_client
        return provider

    def test_call_returns_content(self):
        provider = self._make_provider()
        result = provider.call("Say hello")
        assert result == "hello"

    def test_call_includes_system(self):
        provider = self._make_provider()
        provider.call("prompt", system="be helpful")
        call_args = provider._client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "be helpful"}
        assert messages[1] == {"role": "user", "content": "prompt"}

    def test_call_without_system(self):
        provider = self._make_provider()
        provider.call("prompt")
        call_args = provider._client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_retry_on_transient_error(self):
        provider = self._make_provider()
        provider._max_retries = 3
        provider._client.chat.completions.create.side_effect = [
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))]),
        ]
        with patch("time.sleep"):
            result = provider.call("prompt")
        assert result == "ok"
        assert provider._client.chat.completions.create.call_count == 3

    def test_no_retry_on_auth_error(self):
        from openai import AuthenticationError

        provider = self._make_provider()
        provider._client.chat.completions.create.side_effect = AuthenticationError(
            "bad key", response=MagicMock(status_code=401), body={}
        )
        with pytest.raises(AuthenticationError):
            provider.call("prompt")
        assert provider._client.chat.completions.create.call_count == 1

    def test_raises_after_max_retries(self):
        provider = self._make_provider()
        provider._max_retries = 2
        provider._client.chat.completions.create.side_effect = ConnectionError("fail")
        with patch("time.sleep"), pytest.raises(ConnectionError):
            provider.call("prompt")

    def test_import_error_without_openai(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="pip install engramia"):
            OpenAIProvider()


class TestOpenAIEmbeddings:
    def _make_embeddings(self) -> OpenAIEmbeddings:
        emb = OpenAIEmbeddings.__new__(OpenAIEmbeddings)
        emb._model = "text-embedding-3-small"
        emb._max_retries = 3
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = MagicMock(data=[MagicMock(embedding=[0.1, 0.2, 0.3])])
        emb._client = mock_client
        return emb

    def test_embed_returns_vector(self):
        emb = self._make_embeddings()
        result = emb.embed("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_batch_single_api_call(self):
        emb = self._make_embeddings()
        emb._client.embeddings.create.return_value = MagicMock(
            data=[
                MagicMock(embedding=[0.1, 0.2]),
                MagicMock(embedding=[0.3, 0.4]),
            ]
        )
        results = emb.embed_batch(["a", "b"])
        assert results == [[0.1, 0.2], [0.3, 0.4]]
        assert emb._client.embeddings.create.call_count == 1

    def test_embed_batch_empty(self):
        emb = self._make_embeddings()
        assert emb.embed_batch([]) == []
        emb._client.embeddings.create.assert_not_called()
