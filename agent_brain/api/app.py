"""FastAPI application factory for Agent Brain.

Configuration is entirely via environment variables:

    BRAIN_STORAGE        json | postgres          (default: json)
    BRAIN_DATA_PATH      ./brain_data             (json only)
    BRAIN_DATABASE_URL   postgresql://...         (postgres only)
    BRAIN_LLM_PROVIDER   openai                   (default: openai)
    BRAIN_LLM_MODEL      gpt-4.1                  (default: gpt-4.1)
    OPENAI_API_KEY       sk-...
    BRAIN_EMBEDDING_MODEL text-embedding-3-small  (default)
    BRAIN_API_KEYS       key1,key2                (empty = dev mode, no auth)
    BRAIN_HOST           0.0.0.0                  (default)
    BRAIN_PORT           8000                     (default)

Run:
    uvicorn agent_brain.api.app:app
    # or with docker compose up
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_brain import Brain
from agent_brain.api.routes import router

_log = logging.getLogger(__name__)


def _make_storage():
    backend = os.environ.get("BRAIN_STORAGE", "json").lower()
    if backend == "postgres":
        from agent_brain.providers.postgres import PostgresStorage
        return PostgresStorage()  # reads BRAIN_DATABASE_URL from env
    # Default: JSON storage
    from agent_brain.providers.json_storage import JSONStorage
    path = os.environ.get("BRAIN_DATA_PATH", "./brain_data")
    return JSONStorage(path=path)


def _make_embeddings():
    model = os.environ.get("BRAIN_EMBEDDING_MODEL", "text-embedding-3-small")
    from agent_brain.providers.openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=model)


def _make_llm():
    provider = os.environ.get("BRAIN_LLM_PROVIDER", "openai").lower()
    model = os.environ.get("BRAIN_LLM_MODEL", "gpt-4.1")
    if provider == "openai":
        from agent_brain.providers.openai import OpenAIProvider
        return OpenAIProvider(model=model)
    _log.warning("Unknown BRAIN_LLM_PROVIDER %r — LLM features will be unavailable", provider)
    return None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Called once at startup. The Brain singleton is stored on ``app.state.brain``
    and retrieved per-request via the ``get_brain`` dependency.
    """
    app = FastAPI(
        title="Agent Brain API",
        description=(
            "Self-learning memory layer for AI agent frameworks. "
            "Provides learn, recall, evaluate, compose, and feedback endpoints."
        ),
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    storage = _make_storage()
    embeddings = _make_embeddings()
    llm = _make_llm()

    app.state.brain = Brain(
        embeddings=embeddings,
        storage=storage,
        llm=llm,
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.include_router(router)

    _log.info(
        "Agent Brain API started — storage=%s, llm=%s",
        type(storage).__name__,
        type(llm).__name__ if llm else "None",
    )
    return app


# Module-level app instance for uvicorn / docker.
# Created lazily so that importing this module in tests doesn't
# immediately try to connect to OpenAI / Postgres.
# Uvicorn usage: uvicorn agent_brain.api.app:create_app --factory
# Or: from agent_brain.api.app import app  (triggers creation)
try:
    import os
    _skip_auto_create = os.environ.get("BRAIN_SKIP_AUTO_APP", "0") == "1"
except Exception:
    _skip_auto_create = True

if not _skip_auto_create:
    app = create_app()
