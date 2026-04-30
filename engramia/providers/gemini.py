# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Google Gemini LLM and embedding providers.

Requires the ``gemini`` extra:
    pip install engramia[gemini]

Uses the modern ``google-genai`` SDK (replaces the older
``google-generativeai``). Lazy imports so the module is importable
without the SDK installed — the ImportError is raised at instantiation.

Auth: Gemini uses an API key (env var ``GOOGLE_API_KEY`` for self-hosted
single-tenant fallback, or explicit ``api_key=`` argument for BYOK).
The key is sent as part of the SDK's auth handshake, not as a query
parameter on every call (the validator pings ``?key=`` only).
"""

import logging
import random
import time
from typing import Any

from engramia.providers._concurrency import llm_semaphore
from engramia.providers.base import EmbeddingProvider, LLMProvider
from engramia.telemetry import metrics as _metrics
from engramia.telemetry import tracing as _tracing

_log = logging.getLogger(__name__)

_GEMINI_INSTALL_MSG = "Gemini provider requires the google-genai package. Install it with: pip install engramia[gemini]"


class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini via google-genai SDK.

    Args:
        model: Model ID (default: ``gemini-2.5-flash`` — cheap default;
            override to ``gemini-2.5-pro`` for higher quality).
        max_retries: Number of attempts before raising the last exception.
        max_tokens: Maximum tokens in the response.
        timeout: Per-request timeout in seconds. Currently unused — google-genai
            SDK does not expose per-request timeout cleanly; pass via
            HTTP options if needed in future.
        api_key: Explicit key for BYOK. Falls back to ``GOOGLE_API_KEY``
            env var when None.
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        max_retries: int = 3,
        max_tokens: int = 4096,
        timeout: float = 30.0,
        *,
        api_key: str | None = None,
    ) -> None:
        try:
            from google import genai
        except ImportError:
            raise ImportError(_GEMINI_INSTALL_MSG) from None
        # genai.Client accepts api_key=None and falls back to GOOGLE_API_KEY env
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self._model = model
        self._max_retries = max_retries
        self._max_tokens = max_tokens

    @_tracing.traced("llm.call", {"llm.provider": "gemini"})
    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        # google-genai exception types are namespaced under genai.errors;
        # we lazy-import in the call path to avoid a hard dep at module load.
        from google.genai import errors as _genai_errors

        # System prompt and user prompt are joined into "contents" with a
        # leading system message. The SDK supports a separate `system_instruction`
        # but the join keeps parity with OpenAI/Anthropic providers' behaviour.
        contents = f"{system}\n\n---\n\n{prompt}" if system else prompt

        last_exc: Exception | None = None
        t0 = time.perf_counter()
        with llm_semaphore():
            for attempt in range(self._max_retries):
                try:
                    config: dict[str, Any] = {"max_output_tokens": self._max_tokens}
                    response = self._client.models.generate_content(
                        model=self._model,
                        contents=contents,
                        config=config,
                    )
                    _metrics.observe_llm("gemini", self._model, time.perf_counter() - t0, role)
                    return response.text or ""
                except (
                    _genai_errors.ClientError,
                    _genai_errors.APIError,
                ) as exc:
                    # 4xx errors should not be retried — propagate.
                    status = getattr(exc, "code", None)
                    if status is not None and 400 <= status < 500:
                        raise
                    last_exc = exc
                    if attempt < self._max_retries - 1:
                        _log.warning(
                            "Gemini call failed (attempt %d/%d): %s",
                            attempt + 1,
                            self._max_retries,
                            exc,
                        )
                        time.sleep(2**attempt + random.uniform(0, 1))

        raise last_exc or RuntimeError(f"All {self._max_retries} retries exhausted with no exception recorded")


class GeminiEmbeddings(EmbeddingProvider):
    """Embedding provider backed by Gemini's embedContent API.

    Default model ``gemini-embedding-001`` produces 3072-dim vectors;
    override to lower-dim variants if storage budget is tight (Engramia's
    pgvector schema fixes dimension at HNSW DDL time, so changing model
    requires the embedding-reindex tooling).

    Args:
        model: Embedding model ID. Default ``gemini-embedding-001``.
        max_retries: Retry count.
        api_key: Explicit BYOK key. Falls back to ``GOOGLE_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "gemini-embedding-001",
        max_retries: int = 3,
        timeout: float = 15.0,
        *,
        api_key: str | None = None,
    ) -> None:
        try:
            from google import genai
        except ImportError:
            raise ImportError(_GEMINI_INSTALL_MSG) from None
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self._model = model
        self._max_retries = max_retries

    def _call_with_retry(self, contents: str | list[str]) -> Any:
        from google.genai import errors as _genai_errors

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.models.embed_content(
                    model=self._model,
                    contents=contents,
                )
            except (_genai_errors.ClientError, _genai_errors.APIError) as exc:
                status = getattr(exc, "code", None)
                if status is not None and 400 <= status < 500:
                    raise
                last_exc = exc
                if attempt < self._max_retries - 1:
                    _log.warning(
                        "Gemini embedding failed (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries,
                        exc,
                    )
                    time.sleep(2**attempt + random.uniform(0, 1))
        raise last_exc or RuntimeError(f"All {self._max_retries} embedding retries exhausted")

    @_tracing.traced("embedding.embed", {"embedding.provider": "gemini"})
    def embed(self, text: str) -> list[float]:
        t0 = time.perf_counter()
        response = self._call_with_retry(text)
        _metrics.observe_embedding("gemini", time.perf_counter() - t0)
        # google-genai response.embeddings is a list of EmbedContentResponse
        # entries; for single-input call, take the first.
        return list(response.embeddings[0].values)

    @_tracing.traced("embedding.embed_batch", {"embedding.provider": "gemini"})
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        t0 = time.perf_counter()
        response = self._call_with_retry(texts)
        _metrics.observe_embedding("gemini", time.perf_counter() - t0)
        return [list(e.values) for e in response.embeddings]
