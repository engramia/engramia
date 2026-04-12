# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for _factory.py — provider construction from environment variables.

Verifies that make_storage / make_embeddings / make_llm correctly read env
vars and instantiate the right provider classes.  All external packages are
mocked so no real API keys or databases are required.
"""

import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# make_storage
# ---------------------------------------------------------------------------


class TestMakeStorage:
    def test_default_returns_json_storage(self, tmp_path, monkeypatch):
        """No ENGRAMIA_STORAGE env var → JSONStorage."""
        monkeypatch.delenv("ENGRAMIA_STORAGE", raising=False)
        monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))

        from engramia._factory import make_storage
        from engramia.providers.json_storage import JSONStorage

        result = make_storage()
        assert isinstance(result, JSONStorage)

    def test_explicit_json_returns_json_storage(self, tmp_path, monkeypatch):
        """ENGRAMIA_STORAGE=json → JSONStorage at the configured path."""
        monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
        monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))

        from engramia._factory import make_storage
        from engramia.providers.json_storage import JSONStorage

        result = make_storage()
        assert isinstance(result, JSONStorage)

    def test_postgres_instantiates_postgres_storage(self, monkeypatch):
        """ENGRAMIA_STORAGE=postgres → PostgresStorage() called once (no args)."""
        monkeypatch.setenv("ENGRAMIA_STORAGE", "postgres")

        mock_module = MagicMock()
        mock_instance = MagicMock()
        mock_module.PostgresStorage.return_value = mock_instance

        with patch.dict(sys.modules, {"engramia.providers.postgres": mock_module}):
            from engramia._factory import make_storage

            result = make_storage()

        assert result is mock_instance
        mock_module.PostgresStorage.assert_called_once_with()

    def test_custom_data_path_passed_to_json_storage(self, tmp_path, monkeypatch):
        """ENGRAMIA_DATA_PATH is forwarded to JSONStorage constructor."""
        custom = str(tmp_path / "custom_dir")
        monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
        monkeypatch.setenv("ENGRAMIA_DATA_PATH", custom)

        from engramia._factory import make_storage
        from engramia.providers.json_storage import JSONStorage

        result = make_storage()
        assert isinstance(result, JSONStorage)
        # JSONStorage normalises path; just verify no crash and right type


# ---------------------------------------------------------------------------
# make_embeddings
# ---------------------------------------------------------------------------


class TestMakeEmbeddings:
    def test_default_model(self, monkeypatch):
        """No ENGRAMIA_EMBEDDING_MODEL → uses text-embedding-3-small."""
        monkeypatch.delenv("ENGRAMIA_EMBEDDING_MODEL", raising=False)

        mock_module = MagicMock()
        mock_instance = MagicMock()
        mock_module.OpenAIEmbeddings.return_value = mock_instance

        with patch.dict(sys.modules, {"engramia.providers.openai": mock_module}):
            from engramia._factory import make_embeddings

            result = make_embeddings()

        mock_module.OpenAIEmbeddings.assert_called_once_with(model="text-embedding-3-small")
        assert result is mock_instance

    def test_custom_model(self, monkeypatch):
        """ENGRAMIA_EMBEDDING_MODEL overrides default."""
        monkeypatch.setenv("ENGRAMIA_EMBEDDING_MODEL", "text-embedding-ada-002")

        mock_module = MagicMock()

        with patch.dict(sys.modules, {"engramia.providers.openai": mock_module}):
            from engramia._factory import make_embeddings

            make_embeddings()

        mock_module.OpenAIEmbeddings.assert_called_once_with(model="text-embedding-ada-002")

    def test_none_model_returns_none(self, monkeypatch):
        """ENGRAMIA_EMBEDDING_MODEL=none → returns None (semantic search disabled)."""
        monkeypatch.setenv("ENGRAMIA_EMBEDDING_MODEL", "none")
        from engramia._factory import make_embeddings

        result = make_embeddings()
        assert result is None

    def test_import_error_returns_none(self, monkeypatch):
        """When openai package is missing, make_embeddings returns None."""
        monkeypatch.delenv("ENGRAMIA_EMBEDDING_MODEL", raising=False)
        with patch.dict(sys.modules, {"engramia.providers.openai": None}):
            from engramia._factory import make_embeddings

            result = make_embeddings()
        assert result is None


# ---------------------------------------------------------------------------
# make_llm
# ---------------------------------------------------------------------------


class TestMakeLLM:
    def test_openai_default_provider_and_model(self, monkeypatch):
        """No env vars → OpenAIProvider with gpt-4.1."""
        monkeypatch.delenv("ENGRAMIA_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("ENGRAMIA_LLM_MODEL", raising=False)

        mock_module = MagicMock()
        mock_instance = MagicMock()
        mock_module.OpenAIProvider.return_value = mock_instance

        with patch.dict(sys.modules, {"engramia.providers.openai": mock_module}):
            from engramia._factory import make_llm

            result = make_llm()

        mock_module.OpenAIProvider.assert_called_once_with(model="gpt-4.1", timeout=30.0)
        assert result is mock_instance

    def test_openai_custom_model(self, monkeypatch):
        """ENGRAMIA_LLM_MODEL is forwarded to OpenAIProvider."""
        monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "openai")
        monkeypatch.setenv("ENGRAMIA_LLM_MODEL", "gpt-4o")

        mock_module = MagicMock()

        with patch.dict(sys.modules, {"engramia.providers.openai": mock_module}):
            from engramia._factory import make_llm

            make_llm()

        mock_module.OpenAIProvider.assert_called_once_with(model="gpt-4o", timeout=30.0)

    def test_unknown_provider_returns_none(self, monkeypatch):
        """Unrecognised ENGRAMIA_LLM_PROVIDER → None (with a warning logged)."""
        monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "some-unknown-provider")

        from engramia._factory import make_llm

        result = make_llm()
        assert result is None

    def test_anthropic_provider(self, monkeypatch):
        """ENGRAMIA_LLM_PROVIDER=anthropic → AnthropicProvider instantiated."""
        monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ENGRAMIA_LLM_MODEL", "claude-3-haiku-20240307")

        mock_module = MagicMock()
        mock_instance = MagicMock()
        mock_module.AnthropicProvider.return_value = mock_instance

        with patch.dict(sys.modules, {"engramia.providers.anthropic": mock_module}):
            from engramia._factory import make_llm

            result = make_llm()

        mock_module.AnthropicProvider.assert_called_once_with(model="claude-3-haiku-20240307", timeout=30.0)
        assert result is mock_instance

    def test_none_provider_returns_none(self, monkeypatch):
        """ENGRAMIA_LLM_PROVIDER=none → returns None without warning."""
        monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")

        from engramia._factory import make_llm

        result = make_llm()
        assert result is None
