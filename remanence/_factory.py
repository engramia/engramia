"""Shared Brain provider factory helpers.

Used by both the REST API (api/app.py) and the MCP server (mcp/server.py)
to construct provider instances from environment variables.
"""

import logging
import os

_log = logging.getLogger(__name__)


def make_storage():
    """Create storage backend from REMANENCE_STORAGE / REMANENCE_DATA_PATH env vars."""
    backend = os.environ.get("REMANENCE_STORAGE", "json").lower()
    if backend == "postgres":
        from remanence.providers.postgres import PostgresStorage

        return PostgresStorage()  # reads REMANENCE_DATABASE_URL from env
    from remanence.providers.json_storage import JSONStorage

    path = os.environ.get("REMANENCE_DATA_PATH", "./brain_data")
    return JSONStorage(path=path)


def make_embeddings():
    """Create embedding provider from REMANENCE_EMBEDDING_MODEL env var."""
    model = os.environ.get("REMANENCE_EMBEDDING_MODEL", "text-embedding-3-small")
    from remanence.providers.openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=model)


def make_llm():
    """Create LLM provider from REMANENCE_LLM_PROVIDER / REMANENCE_LLM_MODEL env vars."""
    provider = os.environ.get("REMANENCE_LLM_PROVIDER", "openai").lower()
    model = os.environ.get("REMANENCE_LLM_MODEL", "gpt-4.1")
    if provider == "openai":
        from remanence.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model)
    _log.warning("Unknown REMANENCE_LLM_PROVIDER %r — LLM features will be unavailable", provider)
    return None
