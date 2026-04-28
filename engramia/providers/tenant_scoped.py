# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tenant-scoped LLM and embedding provider wrappers for BYOK.

These wrappers are the bridge between the existing single-instance
Memory facade and the per-tenant credential resolution introduced in
Phase 6.6. The Memory factory builds **one** wrapper at startup; on
every call, the wrapper:

1. Reads the active tenant from :func:`engramia._context.get_scope`.
2. Asks :class:`engramia.credentials.resolver.CredentialResolver` for
   that tenant's credential (LRU+TTL cached internally).
3. Constructs (or reuses) the right concrete provider instance for the
   credential's provider type, and forwards the call.
4. Falls back to :class:`engramia.providers.demo.DemoProvider` when no
   credential exists, so a tenant who skipped onboarding still gets a
   functional (if synthetic) response and a clear "add your LLM key"
   message.

A second-level cache keyed by ``(tenant_id, provider_type, role)``
keeps the SDK client construction (which spins up an httpx connection
pool) out of the hot path. Cache invalidation is delegated to the
resolver — when the resolver invalidates a tenant on credential change,
the next call rebuilds the provider with the rotated key.
"""

from __future__ import annotations

import collections
import logging
import threading
from typing import TYPE_CHECKING, Final

from engramia._context import get_scope
from engramia.providers.base import EmbeddingProvider, LLMProvider
from engramia.providers.demo import DemoProvider

if TYPE_CHECKING:
    from engramia.credentials.models import TenantCredential
    from engramia.credentials.resolver import CredentialResolver

_log = logging.getLogger(__name__)

_PROVIDER_CACHE_MAX: Final[int] = 512


def _build_llm(cred: TenantCredential, role: str) -> LLMProvider:
    """Construct the concrete LLM provider for a credential.

    Lazy imports keep the optional SDK extras optional. When a tenant
    has Anthropic configured but the cloud only has the openai extra
    installed, the route handler raises a clear ImportError instead of
    silently degrading.
    """
    model = cred.model_for_role(role)
    if cred.provider == "openai":
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=cred.api_key, model=model, base_url=cred.base_url)
    if cred.provider == "anthropic":
        from engramia.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=cred.api_key, model=model)
    if cred.provider == "gemini":
        from engramia.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=cred.api_key, model=model)
    if cred.provider == "ollama":
        from engramia.providers.ollama import OllamaProvider

        return OllamaProvider(
            api_key=cred.api_key,
            model=model,
            base_url=cred.base_url or "http://localhost:11434/v1",
        )
    if cred.provider == "openai_compat":
        # OpenAICompat reuses OpenAIProvider with explicit base_url
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=cred.api_key, model=model, base_url=cred.base_url)
    raise ValueError(f"Unknown provider for tenant credential: {cred.provider!r}")


def _build_embeddings(cred: TenantCredential) -> EmbeddingProvider:
    """Construct the concrete embedding provider for a credential."""
    model = cred.default_embed_model or "text-embedding-3-small"
    if cred.provider in ("openai", "openai_compat"):
        from engramia.providers.openai import OpenAIEmbeddings

        return OpenAIEmbeddings(api_key=cred.api_key, model=model, base_url=cred.base_url)
    if cred.provider == "gemini":
        from engramia.providers.gemini import GeminiEmbeddings

        return GeminiEmbeddings(api_key=cred.api_key, model=cred.default_embed_model or "gemini-embedding-001")
    if cred.provider == "ollama":
        from engramia.providers.ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            api_key=cred.api_key,
            model=cred.default_embed_model or "nomic-embed-text",
            base_url=cred.base_url or "http://localhost:11434/v1",
        )
    raise ValueError(
        f"Provider {cred.provider!r} does not offer embeddings — "
        "configure a separate (provider, purpose='embedding') credential."
    )


class TenantScopedLLMProvider(LLMProvider):
    """LLM provider that resolves the underlying provider per request.

    Reads the active tenant from the scope contextvar set by
    ``require_auth`` (or by tests via ``set_scope``). Falls back to a
    shared :class:`DemoProvider` when no credential is configured.

    Args:
        resolver: Bound :class:`CredentialResolver`.
        fallback: Provider used when the resolver returns ``None``.
            Defaults to a fresh :class:`DemoProvider` per app instance.
    """

    def __init__(
        self,
        resolver: CredentialResolver,
        fallback: LLMProvider | None = None,
    ) -> None:
        self._resolver = resolver
        self._fallback = fallback or DemoProvider()
        self._cache: collections.OrderedDict[tuple[str, str, str], LLMProvider] = collections.OrderedDict()
        self._lock = threading.Lock()

    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        scope = get_scope()
        cred = self._resolver.resolve(scope.tenant_id, "llm")
        if cred is None:
            return self._fallback.call(prompt, system=system, role=role)
        provider = self._get_or_build_provider(cred, role)
        return provider.call(prompt, system=system, role=role)

    def invalidate(self, tenant_id: str) -> None:
        """Drop cached concrete providers for a tenant.

        Called from the credential routes after upsert / patch / revoke
        so the next request uses a freshly constructed client. Mirrors
        :meth:`CredentialResolver.invalidate`.
        """
        with self._lock:
            keys = [k for k in self._cache if k[0] == tenant_id]
            for k in keys:
                del self._cache[k]

    def _get_or_build_provider(self, cred: TenantCredential, role: str) -> LLMProvider:
        key = (cred.tenant_id, cred.provider, role)
        with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing
        provider = _build_llm(cred, role)
        with self._lock:
            self._cache[key] = provider
            self._cache.move_to_end(key)
            while len(self._cache) > _PROVIDER_CACHE_MAX:
                self._cache.popitem(last=False)
        return provider


class TenantScopedEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that resolves per request from the scope contextvar.

    When the active tenant has no embedding-capable credential, falls
    back to ``LocalEmbeddings`` (sentence-transformers) so tenants in
    demo mode can still exercise the recall path with a non-trivial
    embedding. The fallback is constructed lazily on first use to avoid
    pulling sentence-transformers into the dependency closure of every
    instance.

    Args:
        resolver: Bound :class:`CredentialResolver`.
        fallback: Optional explicit fallback. None means lazy-build a
            :class:`engramia.providers.local_embeddings.LocalEmbeddings`
            on first cache miss.
    """

    def __init__(
        self,
        resolver: CredentialResolver,
        fallback: EmbeddingProvider | None = None,
    ) -> None:
        self._resolver = resolver
        self._fallback: EmbeddingProvider | None = fallback
        self._fallback_lock = threading.Lock()
        self._cache: collections.OrderedDict[tuple[str, str], EmbeddingProvider] = collections.OrderedDict()
        self._lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        provider = self._resolve_provider()
        return provider.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        provider = self._resolve_provider()
        return provider.embed_batch(texts)

    def invalidate(self, tenant_id: str) -> None:
        """Drop cached concrete providers for a tenant."""
        with self._lock:
            keys = [k for k in self._cache if k[0] == tenant_id]
            for k in keys:
                del self._cache[k]

    def _resolve_provider(self) -> EmbeddingProvider:
        scope = get_scope()
        # Prefer an embedding-purpose credential, then fall back to an LLM
        # credential whose provider also offers embeddings (OpenAI, Gemini,
        # Ollama do; Anthropic does not).
        cred = self._resolver.resolve(scope.tenant_id, "embedding")
        if cred is None:
            cred = self._resolver.resolve(scope.tenant_id, "llm")
            if cred is None or cred.provider == "anthropic":
                return self._get_fallback()
        try:
            return self._get_or_build_embeddings(cred)
        except (ValueError, ImportError) as exc:
            _log.debug(
                "TenantScopedEmbeddingProvider: provider %r has no embeddings (%s) — using fallback",
                cred.provider,
                exc,
            )
            return self._get_fallback()

    def _get_or_build_embeddings(self, cred: TenantCredential) -> EmbeddingProvider:
        key = (cred.tenant_id, cred.provider)
        with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                self._cache.move_to_end(key)
                return existing
        provider = _build_embeddings(cred)
        with self._lock:
            self._cache[key] = provider
            self._cache.move_to_end(key)
            while len(self._cache) > _PROVIDER_CACHE_MAX:
                self._cache.popitem(last=False)
        return provider

    def _get_fallback(self) -> EmbeddingProvider:
        if self._fallback is not None:
            return self._fallback
        with self._fallback_lock:
            if self._fallback is not None:
                return self._fallback
            try:
                from engramia.providers.local_embeddings import LocalEmbeddings

                self._fallback = LocalEmbeddings()
                _log.info("TenantScopedEmbeddingProvider: lazy-initialised LocalEmbeddings fallback.")
            except ImportError as exc:
                raise RuntimeError(
                    "No embedding provider configured for the active tenant and "
                    "sentence-transformers is not installed. Add a credential or "
                    "install: pip install 'engramia[local]'."
                ) from exc
        return self._fallback
