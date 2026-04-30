# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Ollama native HTTP API helpers (separate from OpenAI-compat layer).

Ollama exposes two parallel APIs:

- **OpenAI-compatible** at ``/v1/*`` (chat/completions, embeddings, models)
  — what the openai SDK talks to via ``base_url=http://host:11434/v1``.
  This is what :class:`OllamaProvider` uses for actual inference.
- **Native** at ``/api/*`` (tags, show, pull, generate, embeddings) —
  richer per-model metadata that the OpenAI-compat surface doesn't
  expose (model size, parameter count, quantization, modified_at).

This module is the native layer. It's used for:

- **Validation** — list pulled models, confirm a tenant's
  ``default_model`` is actually present on the server.
- **Per-model timeout heuristics** — large models (70B+) need longer
  timeouts than small ones (1B). Reading param count from
  ``/api/show`` lets the resolver pick a scaled timeout.
- **Model discovery cache** — list ``/api/tags`` once per hour and
  surface the result to the dashboard so the user picks from a
  dropdown instead of typing model names.

Auth: Ollama itself doesn't enforce auth at the HTTP layer. If the
operator has fronted Ollama with a reverse proxy that requires a
bearer token, we forward whatever the credential's ``api_key`` field
holds (typically the literal placeholder ``"ollama"``).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

import httpx

_log = logging.getLogger(__name__)

# Per-call timeouts. The native API is much lighter than chat completions
# (no LLM inference), so 5 s is plenty.
_NATIVE_HTTP_TIMEOUT_S: Final[float] = 5.0

# Model-list cache TTL. Ollama operators rarely pull new models more than
# a couple times a day, and the dashboard surfacing wants quick refresh
# but not a hot path on every credential resolution.
_MODEL_LIST_TTL_S: Final[float] = 3_600.0  # 1 hour


@dataclass(frozen=True)
class OllamaModel:
    """One row from Ollama's ``/api/tags`` response.

    Attributes:
        name: Full model name with optional tag, e.g. ``"llama3.3:latest"``,
            ``"qwen2.5-coder:7b"``.
        size_bytes: Disk size of the model. ``None`` when ``/api/tags``
            doesn't include it (some Ollama versions omit ``size``).
        param_count: Parameter count from ``/api/show``, e.g. ``"7B"``,
            ``"70B"``. ``None`` when not fetched (lazy — only filled in
            when the resolver asks for per-model timeout sizing).
        quantization: Quantisation marker like ``"Q4_K_M"``. ``None``
            when not exposed.
    """

    name: str
    size_bytes: int | None = None
    param_count: str | None = None
    quantization: str | None = None


def native_base_url(base_url: str) -> str:
    """Normalise a credential's ``base_url`` to the native API root.

    Tenants typically save ``http://host:11434/v1`` (the OpenAI-compat
    suffix the openai SDK needs). The native API lives under ``/api`` at
    the same host without the ``/v1`` suffix. This helper strips one
    trailing ``/v1`` so both formats round-trip correctly:

    >>> native_base_url("http://localhost:11434/v1")
    'http://localhost:11434'
    >>> native_base_url("http://localhost:11434")
    'http://localhost:11434'
    >>> native_base_url("http://example.com:8080/v1/")
    'http://example.com:8080'
    """
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/v1"):
        cleaned = cleaned[: -len("/v1")]
    return cleaned


def list_models(base_url: str, *, timeout: float = _NATIVE_HTTP_TIMEOUT_S) -> list[OllamaModel]:
    """List models pulled on the Ollama server.

    Calls ``GET {native_base_url}/api/tags``. Returns an empty list if
    the server has no models. Raises :class:`httpx.HTTPError` (or its
    subclasses :class:`httpx.TimeoutException` / :class:`httpx.ConnectError`)
    on transport failure — callers translate these to ``unreachable``
    validation results.

    Args:
        base_url: The credential's ``base_url`` field. Either format
            (``host:11434`` or ``host:11434/v1``) is accepted.
        timeout: Per-request timeout in seconds (default 5 s).

    Returns:
        List of :class:`OllamaModel` ordered as the server returned them.
    """
    url = f"{native_base_url(base_url)}/api/tags"
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    out: list[OllamaModel] = []
    for entry in body.get("models", []):
        details = entry.get("details") or {}
        out.append(
            OllamaModel(
                name=entry.get("name", ""),
                size_bytes=entry.get("size"),
                param_count=details.get("parameter_size"),
                quantization=details.get("quantization_level"),
            )
        )
    return out


def show_model(
    base_url: str,
    model_name: str,
    *,
    timeout: float = _NATIVE_HTTP_TIMEOUT_S,
) -> dict | None:
    """Fetch full metadata for one model via ``POST /api/show``.

    Used by the per-model timeout heuristic when the resolver needs the
    parameter count for a model that ``/api/tags`` returned without
    details. Returns ``None`` when the model isn't pulled (404).
    """
    url = f"{native_base_url(base_url)}/api/show"
    try:
        resp = httpx.post(url, json={"name": model_name}, timeout=timeout)
    except httpx.HTTPError:
        return None
    if resp.status_code == 404:
        return None
    if not resp.is_success:
        return None
    return resp.json()


def model_is_pulled(models: list[OllamaModel], wanted: str) -> bool:
    """Match a wanted model name against the pulled list.

    Ollama tags are sticky: ``llama3.3`` is shorthand for
    ``llama3.3:latest``. Tenants typically save the bare name in
    ``default_model``, so we treat the bare form as matching the
    ``:latest`` variant.

    >>> from engramia.providers._ollama_native import OllamaModel
    >>> pulled = [OllamaModel(name="llama3.3:latest"), OllamaModel(name="qwen2.5:7b")]
    >>> model_is_pulled(pulled, "llama3.3")
    True
    >>> model_is_pulled(pulled, "llama3.3:latest")
    True
    >>> model_is_pulled(pulled, "qwen2.5:7b")
    True
    >>> model_is_pulled(pulled, "missing")
    False
    """
    if not wanted:
        return True  # nothing to verify
    names = {m.name for m in models}
    if wanted in names:
        return True
    return ":" not in wanted and f"{wanted}:latest" in names


# ---------------------------------------------------------------------------
# Per-server model-list cache
# ---------------------------------------------------------------------------


@dataclass
class _CachedModelList:
    models: list[OllamaModel]
    fetched_at: float


class OllamaModelCache:
    """Process-local TTL cache of ``/api/tags`` results per Ollama server.

    Keyed by the **native** base URL (post-normalisation), so two
    credentials pointing at the same Ollama instance via different
    suffixes share the cache. Thread-safe via :class:`threading.Lock`.

    The cache is invalidated explicitly by the dashboard's
    ``POST /v1/credentials/{id}/refresh-models`` (when added) and
    implicitly by TTL expiry (1 h default). Capacity is intentionally
    small — most tenants point at one Ollama server.
    """

    def __init__(self, ttl_s: float = _MODEL_LIST_TTL_S) -> None:
        self._ttl_s = ttl_s
        self._cache: dict[str, _CachedModelList] = {}
        self._lock = threading.Lock()

    def get(self, base_url: str) -> list[OllamaModel] | None:
        """Return cached models for the server, or ``None`` if missing/expired."""
        key = native_base_url(base_url)
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if now - entry.fetched_at > self._ttl_s:
                del self._cache[key]
                return None
            return entry.models

    def put(self, base_url: str, models: list[OllamaModel]) -> None:
        key = native_base_url(base_url)
        with self._lock:
            self._cache[key] = _CachedModelList(models=models, fetched_at=time.time())

    def invalidate(self, base_url: str) -> None:
        """Drop the cached entry for one server (e.g. after a model pull)."""
        key = native_base_url(base_url)
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        """Drop all cached entries. Intended for tests + master-key rotation."""
        with self._lock:
            self._cache.clear()


# Process-wide singleton — the dashboard, validator, and resolver all read
# the same cache so they don't issue duplicate /api/tags requests.
_default_cache = OllamaModelCache()


def get_default_cache() -> OllamaModelCache:
    """Return the process-wide model-list cache."""
    return _default_cache


# ---------------------------------------------------------------------------
# Per-model timeout heuristic
# ---------------------------------------------------------------------------

# Mapping from ``parameter_size`` strings (Ollama exposes "7B", "70B", etc.)
# to the recommended per-call timeout in seconds. The values come from
# rough cold-load + first-token latency observed on a single A4000 / RTX
# 4090. They're upper bounds — Ollama-on-CPU users have to live with the
# 70B+ ceiling regardless. Operators can override via OllamaProvider's
# ``timeout`` constructor arg.
_TIMEOUT_BY_PARAM_SIZE: Final[dict[str, float]] = {
    "0.5B": 60.0,
    "1B": 60.0,
    "1.5B": 60.0,
    "2B": 90.0,
    "3B": 90.0,
    "7B": 120.0,
    "8B": 120.0,
    "13B": 180.0,
    "14B": 180.0,
    "32B": 300.0,
    "34B": 300.0,
    "70B": 600.0,
    "72B": 600.0,
    "405B": 1800.0,
}

# When a parameter_size string is unknown (custom GGUF, future model
# families), fall back to this conservative cap.
_DEFAULT_OLLAMA_TIMEOUT_S: Final[float] = 300.0


def recommended_timeout(param_size: str | None) -> float:
    """Map a model's parameter-count string to a per-call timeout.

    >>> recommended_timeout("7B")
    120.0
    >>> recommended_timeout("70B")
    600.0
    >>> recommended_timeout(None)
    300.0
    >>> recommended_timeout("999B-custom")
    300.0
    """
    if param_size is None:
        return _DEFAULT_OLLAMA_TIMEOUT_S
    return _TIMEOUT_BY_PARAM_SIZE.get(param_size, _DEFAULT_OLLAMA_TIMEOUT_S)


# ---------------------------------------------------------------------------
# Reachability check
# ---------------------------------------------------------------------------


def is_reachable(base_url: str, *, timeout: float = _NATIVE_HTTP_TIMEOUT_S) -> bool:
    """Quick liveness check against ``/api/version``.

    Used by the credential validator before the heavier ``/api/tags``
    call. Returns ``False`` on any transport failure (timeout, refused,
    DNS) so the caller produces a single ``unreachable`` result instead
    of stack-tracing.
    """
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return False
    url = f"{native_base_url(base_url)}/api/version"
    try:
        resp = httpx.get(url, timeout=timeout)
    except httpx.HTTPError:
        return False
    return resp.is_success
