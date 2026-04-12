# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""OpenAI provider implementations.

Requires the ``openai`` extra:
    pip install engramia[openai]

Both providers use lazy imports so the module can be imported without the
``openai`` package installed — the ImportError is raised at instantiation.
"""

import logging
import random
import time
from typing import Any, cast

from engramia.providers._concurrency import llm_semaphore
from engramia.providers.base import EmbeddingProvider, LLMProvider
from engramia.telemetry import metrics as _metrics
from engramia.telemetry import tracing as _tracing

_log = logging.getLogger(__name__)

_OPENAI_INSTALL_MSG = "OpenAI providers require the openai package. Install it with: pip install engramia[openai]"

#: Errors that should not be retried (client-side mistakes).
_NO_RETRY_STATUS = {400, 401, 403}


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI Chat Completions.

    Handles retries with exponential backoff. Does not retry on
    authentication, permission, or bad-request errors.

    Args:
        model: Model ID to use (default: ``gpt-4.1``).
        max_retries: Number of attempts before raising the last exception.
    """

    def __init__(
        self,
        model: str = "gpt-4.1",
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        try:
            from openai import OpenAI

            self._client = OpenAI(timeout=timeout)
        except ImportError:
            raise ImportError(_OPENAI_INSTALL_MSG) from None
        self._model = model
        self._max_retries = max_retries

    @_tracing.traced("llm.call", {"llm.provider": "openai"})
    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        from openai import AuthenticationError, BadRequestError, PermissionDeniedError

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_exc: Exception | None = None
        t0 = time.perf_counter()
        with llm_semaphore():
            for attempt in range(self._max_retries):
                try:
                    response = self._client.chat.completions.create(
                        model=self._model,
                        messages=cast("list[Any]", messages),
                    )
                    _metrics.observe_llm("openai", self._model, time.perf_counter() - t0)
                    return response.choices[0].message.content or ""
                except (AuthenticationError, BadRequestError, PermissionDeniedError):
                    raise
                except Exception as exc:
                    last_exc = exc
                    if attempt < self._max_retries - 1:
                        _log.warning("OpenAI call failed (attempt %d/%d): %s", attempt + 1, self._max_retries, exc)
                        time.sleep(2**attempt + random.uniform(0, 1))

        raise last_exc or RuntimeError(f"All {self._max_retries} retries exhausted with no exception recorded")


class OpenAIEmbeddings(EmbeddingProvider):
    """Embedding provider backed by OpenAI Embeddings API.

    Supports native batch embedding for efficiency — a single API call
    for multiple texts instead of N sequential calls.

    Args:
        model: Embedding model ID (default: ``text-embedding-3-small``).
            Produces 1536-dimensional vectors.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        try:
            from openai import OpenAI

            self._client = OpenAI(timeout=timeout)
        except ImportError:
            raise ImportError(_OPENAI_INSTALL_MSG) from None
        self._model = model
        self._max_retries = max_retries

    def _call_with_retry(self, input_data: str | list[str]) -> Any:
        """Call the embeddings API with exponential backoff on transient errors."""
        from openai import AuthenticationError, BadRequestError, PermissionDeniedError

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.embeddings.create(model=self._model, input=input_data)
            except (AuthenticationError, BadRequestError, PermissionDeniedError):
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    _log.warning("OpenAI embedding failed (attempt %d/%d): %s", attempt + 1, self._max_retries, exc)
                    time.sleep(2**attempt + random.uniform(0, 1))
        raise last_exc or RuntimeError(f"All {self._max_retries} embedding retries exhausted")

    @_tracing.traced("embedding.embed", {"embedding.provider": "openai"})
    def embed(self, text: str) -> list[float]:
        t0 = time.perf_counter()
        response = self._call_with_retry(text)
        _metrics.observe_embedding("openai", time.perf_counter() - t0)
        return response.data[0].embedding

    @_tracing.traced("embedding.embed_batch", {"embedding.provider": "openai"})
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single API call.

        OpenAI accepts a list of strings as ``input``, returning results
        in the same order. Overrides the default sequential implementation.
        """
        if not texts:
            return []
        t0 = time.perf_counter()
        response = self._call_with_retry(texts)
        _metrics.observe_embedding("openai", time.perf_counter() - t0)
        # OpenAI guarantees results are in the same order as the input list.
        return [item.embedding for item in response.data]
