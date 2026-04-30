# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared Engramia provider factory helpers.

Used by both the REST API (api/app.py) and the MCP server (mcp/server.py)
to construct provider instances.

Two modes:

- **Self-hosted / single-tenant** (default): providers are built from
  process-wide environment variables — ``OPENAI_API_KEY``, ``ENGRAMIA_LLM_MODEL``,
  etc. One provider instance per process; the Memory facade reuses it
  for every request.

- **BYOK / multi-tenant cloud** (``ENGRAMIA_BYOK_ENABLED=true``): the
  ``make_llm`` and ``make_embeddings`` helpers return a thin wrapper
  (:class:`TenantScopedLLMProvider` /
  :class:`TenantScopedEmbeddingProvider`) that resolves the active
  tenant's credential per call via :class:`CredentialResolver`. The
  caller passes the resolver to the factory; if a tenant has no
  credential, the wrapper falls back to :class:`DemoProvider`.

The factory itself does not read ``ENGRAMIA_BYOK_ENABLED`` — that flag
is read in ``api/app.py`` so the wiring decision is observable in the
startup log. The factory just exposes the option of passing a
``resolver`` argument, which is what flips the behaviour.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engramia.billing.role_metering import RoleMeter
    from engramia.credentials.resolver import CredentialResolver
    from engramia.credentials.store import CredentialStore
    from engramia.providers.base import EmbeddingProvider, LLMProvider

_log = logging.getLogger(__name__)


def make_storage():
    """Create storage backend from ENGRAMIA_STORAGE / ENGRAMIA_DATA_PATH env vars."""
    backend = os.environ.get("ENGRAMIA_STORAGE", "json").lower()
    if backend == "postgres":
        from engramia.providers.postgres import PostgresStorage

        return PostgresStorage()  # reads ENGRAMIA_DATABASE_URL from env
    from engramia.providers.json_storage import JSONStorage

    path = os.environ.get("ENGRAMIA_DATA_PATH", "./engramia_data")
    return JSONStorage(path=path)


def make_embeddings(resolver: CredentialResolver | None = None) -> EmbeddingProvider | None:
    """Create an embedding provider.

    Args:
        resolver: When provided, returns a
            :class:`TenantScopedEmbeddingProvider` that resolves
            credentials per request. Used in BYOK / cloud mode.
            When ``None`` (default), falls back to the env-var-driven
            single-instance path used by self-hosted deployments.

    Returns:
        An :class:`EmbeddingProvider` or ``None`` when
        ``ENGRAMIA_EMBEDDING_MODEL=none`` (semantic search disabled).
    """
    if resolver is not None:
        from engramia.providers.tenant_scoped import TenantScopedEmbeddingProvider

        _log.info("Embedding provider: TenantScopedEmbeddingProvider (BYOK mode).")
        return TenantScopedEmbeddingProvider(resolver=resolver)

    model = os.environ.get("ENGRAMIA_EMBEDDING_MODEL", "text-embedding-3-small")
    if model.lower() == "none":
        _log.info("ENGRAMIA_EMBEDDING_MODEL=none — semantic search disabled")
        return None
    try:
        from engramia.providers.openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model)
    except ImportError:
        _log.warning(
            "openai package not installed — semantic search disabled. Install with: pip install 'engramia[openai]'"
        )
        return None


def make_llm(
    resolver: CredentialResolver | None = None,
    store: CredentialStore | None = None,
    role_meter: RoleMeter | None = None,
) -> LLMProvider | None:
    """Create an LLM provider.

    Args:
        resolver: When provided, returns a
            :class:`TenantScopedLLMProvider` that dispatches per-request
            to the credential-resolved provider, falling back to
            :class:`DemoProvider` when no credential exists. Used in
            BYOK / cloud mode.
            When ``None`` (default), falls back to the env-var-driven
            single-instance path used by self-hosted deployments.
        store: Optional credential store for failover_chain resolution
            (Phase 6.6 #2). Without it, failover is silently disabled.
        role_meter: Optional :class:`RoleMeter` enabling the per-role
            cost ceiling preflight gate (Phase 6.6 #2b). Without it,
            ceilings are not enforced — useful in dev / JSON-storage
            mode where there is no DB to back the spend counter.

    Returns:
        An :class:`LLMProvider` or ``None`` when
        ``ENGRAMIA_LLM_PROVIDER=none``.

    Env vars consumed (self-hosted mode only):
        ENGRAMIA_LLM_PROVIDER  openai | anthropic | none  (default: openai)
        ENGRAMIA_LLM_MODEL     model id  (default: gpt-4.1)
        ENGRAMIA_LLM_TIMEOUT   seconds   (default: 30.0)
    """
    if resolver is not None:
        from engramia.providers.tenant_scoped import TenantScopedLLMProvider

        _log.info("LLM provider: TenantScopedLLMProvider (BYOK mode).")
        return TenantScopedLLMProvider(
            resolver=resolver,
            store=store,
            role_meter=role_meter,
        )

    provider = os.environ.get("ENGRAMIA_LLM_PROVIDER", "openai").lower()
    model = os.environ.get("ENGRAMIA_LLM_MODEL", "gpt-4.1")
    timeout = float(os.environ.get("ENGRAMIA_LLM_TIMEOUT", "30.0"))
    if provider == "openai":
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model, timeout=timeout)
    if provider == "anthropic":
        from engramia.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=model, timeout=timeout)
    if provider == "gemini":
        from engramia.providers.gemini import GeminiProvider

        return GeminiProvider(model=model, timeout=timeout)
    if provider != "none":
        _log.warning("Unknown ENGRAMIA_LLM_PROVIDER %r — LLM features will be unavailable", provider)
    return None
