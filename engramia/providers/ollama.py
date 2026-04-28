# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Ollama LLM and embedding providers via the OpenAI-compatible endpoint.

Status: **use-at-own-risk** for v0.7. Native Ollama support (model
auto-discovery via ``/api/tags``, hot-reload, per-model timeouts) is on
the Phase 6.6 #4 roadmap. The current implementation reuses the OpenAI
SDK against ``base_url=http://host:11434/v1`` because Ollama implements
the OpenAI Chat Completions and Embeddings APIs directly.

Why subclass instead of wrap:

- Ollama models are typically slower than hosted APIs (CPU inference,
  cold-load delays). We bump the default timeout to 5 minutes.
- Ollama doesn't enforce auth at the endpoint level — any non-empty
  string in ``Authorization: Bearer`` is accepted. We pass the literal
  ``"ollama"`` placeholder unless the operator has fronted Ollama with
  a reverse proxy that requires a real token.

Limitations to document for tenants:

- No retry on partial token-by-token streams (we use sync calls).
- Tool/function-calling support depends on the loaded model (Llama 3.x,
  Qwen 2.5, DeepSeek-V3 work; older models silently ignore tools).
- Ollama does not implement the OpenAI Embeddings API for every model
  — embedding requires a model with embedding support (e.g. ``nomic-embed-text``,
  ``mxbai-embed-large``).
"""

from __future__ import annotations

import logging
from typing import Final

from engramia.providers.openai import OpenAIEmbeddings, OpenAIProvider

_log = logging.getLogger(__name__)

_OLLAMA_DEFAULT_BASE_URL: Final[str] = "http://localhost:11434/v1"
_OLLAMA_DEFAULT_TIMEOUT: Final[float] = 300.0  # 5 minutes — slow CPU inference
_OLLAMA_BEARER_PLACEHOLDER: Final[str] = "ollama"


class OllamaProvider(OpenAIProvider):
    """LLM provider for Ollama via its OpenAI-compatible Chat Completions endpoint.

    Args:
        model: Ollama model name (must be already pulled on the server,
            e.g. ``llama3.3``, ``qwen2.5-coder``, ``deepseek-r1``).
        base_url: Ollama server URL with ``/v1`` suffix
            (default: ``http://localhost:11434/v1``).
        max_retries: Retry count.
        timeout: Per-request timeout. Default 5 minutes — Ollama CPU
            inference can be slow on first cold load.
        api_key: Bearer placeholder (default: ``"ollama"``). Pass a real
            token only if the operator has fronted Ollama with an auth
            proxy that enforces it.
    """

    def __init__(
        self,
        model: str = "llama3.3",
        base_url: str = _OLLAMA_DEFAULT_BASE_URL,
        max_retries: int = 3,
        timeout: float = _OLLAMA_DEFAULT_TIMEOUT,
        *,
        api_key: str = _OLLAMA_BEARER_PLACEHOLDER,
    ) -> None:
        super().__init__(
            model=model,
            max_retries=max_retries,
            timeout=timeout,
            api_key=api_key,
            base_url=base_url,
        )


class OllamaEmbeddings(OpenAIEmbeddings):
    """Embedding provider for Ollama via its OpenAI-compatible Embeddings endpoint.

    Note: Not all Ollama models implement the Embeddings API. Use
    ``nomic-embed-text``, ``mxbai-embed-large``, or another embedding-capable
    model.

    Args:
        model: Ollama embedding model (default: ``nomic-embed-text``).
        base_url: Ollama server URL with ``/v1`` suffix.
        timeout: Per-request timeout (default 60 s — embeddings are
            faster than generation but still slow on CPU).
        max_retries: Retry count.
        api_key: Bearer placeholder.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = _OLLAMA_DEFAULT_BASE_URL,
        timeout: float = 60.0,
        max_retries: int = 3,
        *,
        api_key: str = _OLLAMA_BEARER_PLACEHOLDER,
    ) -> None:
        super().__init__(
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            api_key=api_key,
            base_url=base_url,
        )
