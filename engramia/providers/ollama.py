# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Ollama LLM and embedding providers via the OpenAI-compatible endpoint.

Status: **supported** as of Phase 6.6 #4 (2026-04-29). Native model
discovery (``/api/tags``), pulled-model validation, and per-model
timeout heuristics ship with this version. Earlier "use-at-own-risk"
disclaimer removed.

Ollama exposes two parallel HTTP APIs at the same host: an
OpenAI-compatible surface at ``/v1/*`` (chat completions, embeddings)
and a native surface at ``/api/*`` (tags, show, pull). Engramia uses
the OpenAI-compat surface for inference (so the openai SDK + retry
logic + telemetry hooks all work uncahnged) and the native surface for
validation, model discovery, and per-model sizing — see
:mod:`engramia.providers._ollama_native`.

Auth: Ollama doesn't enforce auth at the endpoint level; any non-empty
string in ``Authorization: Bearer`` is accepted. We pass the literal
``"ollama"`` placeholder unless the operator has fronted Ollama with
a reverse proxy that requires a real token.

Operational notes:

- **Per-model timeout** — large models (70B+) need substantially
  longer timeouts than small ones (1B). When a credential is created
  via :class:`engramia.providers.tenant_scoped.TenantScopedLLMProvider`,
  the resolver uses :func:`_ollama_native.recommended_timeout` to size
  the timeout based on the model's parameter count.
- **Model list cache** — :func:`OllamaProvider.list_models()` returns a
  process-wide cached snapshot of the Ollama server's pulled models
  (TTL 1 h). Used by the dashboard's model dropdown and by the
  resolver when it needs to verify a tenant's ``role_models`` mapping.
- **No streaming** — Engramia uses sync calls; tool-calling depends
  on the loaded model (Llama 3.x, Qwen 2.5, DeepSeek-V3 work; older
  models silently ignore tools).
- **Embeddings need a capable model** — ``nomic-embed-text``,
  ``mxbai-embed-large``, etc. The OpenAI Embeddings surface returns
  400 on models without embed support; the validator surfaces that as
  ``model_missing``.
"""

from __future__ import annotations

import logging
from typing import Final

from engramia.providers._ollama_native import (
    OllamaModel,
    get_default_cache,
    list_models,
    recommended_timeout,
    show_model,
)
from engramia.providers.openai import OpenAIEmbeddings, OpenAIProvider

_log = logging.getLogger(__name__)

_OLLAMA_DEFAULT_BASE_URL: Final[str] = "http://localhost:11434/v1"
_OLLAMA_DEFAULT_TIMEOUT: Final[float] = 300.0  # 5 min — conservative cap when param size unknown
_OLLAMA_BEARER_PLACEHOLDER: Final[str] = "ollama"


class OllamaProvider(OpenAIProvider):
    """LLM provider for Ollama via its OpenAI-compatible Chat Completions endpoint.

    Args:
        model: Ollama model name (must already be pulled on the server,
            e.g. ``llama3.3``, ``qwen2.5-coder``, ``deepseek-r1``). The
            credential validator catches a missing model at create-time
            so this constructor doesn't re-check.
        base_url: Ollama server URL with ``/v1`` suffix
            (default: ``http://localhost:11434/v1``).
        max_retries: Retry count.
        timeout: Per-request timeout. ``None`` (default) means "auto-size
            from the model's parameter count via /api/show", falling
            back to 5 min when the metadata isn't available. Operators
            who need a hard cap (e.g. user-facing dashboards that can't
            wait 10 min for a 70B response) pass an explicit value.
        api_key: Bearer placeholder (default: ``"ollama"``). Pass a real
            token only if the operator has fronted Ollama with an auth
            proxy that enforces it.
    """

    def __init__(
        self,
        model: str = "llama3.3",
        base_url: str = _OLLAMA_DEFAULT_BASE_URL,
        max_retries: int = 3,
        timeout: float | None = None,
        *,
        api_key: str = _OLLAMA_BEARER_PLACEHOLDER,
    ) -> None:
        resolved_timeout = timeout if timeout is not None else self._auto_timeout(base_url, model)
        super().__init__(
            model=model,
            max_retries=max_retries,
            timeout=resolved_timeout,
            api_key=api_key,
            base_url=base_url,
        )
        self._native_base_url = base_url

    @staticmethod
    def _auto_timeout(base_url: str, model: str) -> float:
        """Look up the model's parameter count on the Ollama server and
        return the matching recommended timeout. Falls back to the
        conservative default when ``/api/show`` is unreachable or
        omits parameter_size."""
        try:
            details = show_model(base_url, model)
        except Exception:
            return _OLLAMA_DEFAULT_TIMEOUT
        if not details:
            return _OLLAMA_DEFAULT_TIMEOUT
        param_size = (details.get("details") or {}).get("parameter_size")
        return recommended_timeout(param_size)

    def list_models(self, *, force_refresh: bool = False) -> list[OllamaModel]:
        """Return the cached list of pulled models on this Ollama server.

        Hits ``/api/tags`` once per hour (TTL on the process-wide cache).
        Pass ``force_refresh=True`` to bypass the cache — used by the
        dashboard's "Refresh models" button after the operator pulls a
        new model.

        Raises :class:`httpx.HTTPError` on transport failure — callers
        should treat that as "Ollama server unreachable, fall back".
        """
        cache = get_default_cache()
        if not force_refresh:
            cached = cache.get(self._native_base_url)
            if cached is not None:
                return cached
        models = list_models(self._native_base_url)
        cache.put(self._native_base_url, models)
        return models


class OllamaEmbeddings(OpenAIEmbeddings):
    """Embedding provider for Ollama via its OpenAI-compatible Embeddings endpoint.

    Note: Not all Ollama models implement the Embeddings API. Use
    ``nomic-embed-text``, ``mxbai-embed-large``, or another embedding-capable
    model. The credential validator catches a non-embed-capable model at
    create-time when a tenant sets ``default_embed_model``.

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
