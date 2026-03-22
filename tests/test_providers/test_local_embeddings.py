"""Tests for LocalEmbeddings provider (mocked, no model download needed)."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestLocalEmbeddings:
    """Tests for the local sentence-transformers embedding provider."""

    def test_import_error_without_package(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with pytest.raises(ImportError, match="sentence-transformers"):
                import importlib
                import agent_brain.providers.local_embeddings as mod
                importlib.reload(mod)
                mod.LocalEmbeddings()

    def test_embed_returns_list_of_floats(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        from agent_brain.providers.local_embeddings import LocalEmbeddings
        provider = LocalEmbeddings.__new__(LocalEmbeddings)
        provider._model = mock_model
        provider._model_name = "test-model"

        result = provider.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(v, float) for v in result)

    def test_embed_batch_returns_list_of_vectors(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array(
            [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]], dtype=np.float32
        )

        from agent_brain.providers.local_embeddings import LocalEmbeddings
        provider = LocalEmbeddings.__new__(LocalEmbeddings)
        provider._model = mock_model
        provider._model_name = "test-model"

        result = provider.embed_batch(["a", "b", "c"])
        assert len(result) == 3
        assert all(len(v) == 2 for v in result)

    def test_embed_batch_empty_list(self):
        from agent_brain.providers.local_embeddings import LocalEmbeddings
        provider = LocalEmbeddings.__new__(LocalEmbeddings)
        provider._model = MagicMock()
        provider._model_name = "test-model"

        result = provider.embed_batch([])
        assert result == []
