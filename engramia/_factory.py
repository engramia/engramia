# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared Engramia provider factory helpers.

Used by both the REST API (api/app.py) and the MCP server (mcp/server.py)
to construct provider instances from environment variables.
"""

import logging
import os

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


def make_embeddings():
    """Create embedding provider from ENGRAMIA_EMBEDDING_MODEL env var.

    Returns None when ENGRAMIA_EMBEDDING_MODEL is set to "none" or when the
    required provider package (openai) is not installed.  The API will start
    without semantic-search features in either case.
    """
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


def make_llm():
    """Create LLM provider from ENGRAMIA_LLM_PROVIDER / ENGRAMIA_LLM_MODEL env vars.

    Timeout is configurable via ENGRAMIA_LLM_TIMEOUT (seconds, default 30.0).
    """
    provider = os.environ.get("ENGRAMIA_LLM_PROVIDER", "openai").lower()
    model = os.environ.get("ENGRAMIA_LLM_MODEL", "gpt-4.1")
    timeout = float(os.environ.get("ENGRAMIA_LLM_TIMEOUT", "30.0"))
    if provider == "openai":
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model, timeout=timeout)
    if provider == "anthropic":
        from engramia.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model=model, timeout=timeout)
    if provider != "none":
        _log.warning("Unknown ENGRAMIA_LLM_PROVIDER %r — LLM features will be unavailable", provider)
    return None
