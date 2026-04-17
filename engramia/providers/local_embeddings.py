# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Local embedding provider using sentence-transformers.

Requires the ``local`` extra:
    pip install engramia[local]

Runs entirely on the local machine — no API key needed.
Useful for open-source deployments and offline use.

Default model: ``all-MiniLM-L6-v2`` (384-dim, fast, good quality).

Note: Embedding dimensions differ from OpenAI (384 vs 1536).
      You cannot mix providers within the same storage — choose one
      and stick with it. JSONStorage enforces dimension consistency.
"""

import logging
import time

from engramia.providers.base import EmbeddingProvider
from engramia.telemetry import metrics as _metrics

_log = logging.getLogger(__name__)

_INSTALL_MSG = "Local embeddings require sentence-transformers. Install with: pip install engramia[local]"


class LocalEmbeddings(EmbeddingProvider):
    """Embedding provider using sentence-transformers (local, no API key).

    Args:
        model: HuggingFace model name or path.
            Default: ``all-MiniLM-L6-v2`` (384-dim, ~80 MB).
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model)
        except ImportError:
            raise ImportError(_INSTALL_MSG) from None
        self._model_name = model
        _log.info("Loaded local embedding model: %s", model)

    def embed(self, text: str) -> list[float]:
        t0 = time.perf_counter()
        vector = self._model.encode(text, convert_to_numpy=True)
        _metrics.observe_embedding("local", time.perf_counter() - t0)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single batch.

        sentence-transformers natively supports batch encoding,
        which is significantly faster than sequential calls.
        """
        if not texts:
            return []
        t0 = time.perf_counter()
        vectors = self._model.encode(texts, convert_to_numpy=True)
        _metrics.observe_embedding("local", time.perf_counter() - t0)
        return [v.tolist() for v in vectors]
