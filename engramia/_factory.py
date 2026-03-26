"""Shared Brain provider factory helpers.

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

    path = os.environ.get("ENGRAMIA_DATA_PATH", "./brain_data")
    return JSONStorage(path=path)


def make_embeddings():
    """Create embedding provider from ENGRAMIA_EMBEDDING_MODEL env var."""
    model = os.environ.get("ENGRAMIA_EMBEDDING_MODEL", "text-embedding-3-small")
    from engramia.providers.openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=model)


def make_llm():
    """Create LLM provider from ENGRAMIA_LLM_PROVIDER / ENGRAMIA_LLM_MODEL env vars."""
    provider = os.environ.get("ENGRAMIA_LLM_PROVIDER", "openai").lower()
    model = os.environ.get("ENGRAMIA_LLM_MODEL", "gpt-4.1")
    if provider == "openai":
        from engramia.providers.openai import OpenAIProvider

        return OpenAIProvider(model=model)
    _log.warning("Unknown ENGRAMIA_LLM_PROVIDER %r — LLM features will be unavailable", provider)
    return None
