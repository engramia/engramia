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

Security configuration (env vars):
    BRAIN_CORS_ORIGINS       comma-separated allowed origins (default: * in dev)
    BRAIN_RATE_LIMIT_DEFAULT requests/min for regular endpoints (default: 60)
    BRAIN_RATE_LIMIT_EXPENSIVE requests/min for LLM endpoints (default: 10)
    BRAIN_MAX_BODY_SIZE      max request body in bytes (default: 1048576 = 1MB)

Run:
    uvicorn agent_brain.api.app:create_app --factory
    # or with docker compose up
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent_brain import Brain
from agent_brain.api.routes import router
from agent_brain.exceptions import ValidationError as BrainValidationError

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


def _log_security_config() -> None:
    """Emit startup warnings for insecure defaults."""
    api_keys_set = bool(os.environ.get("BRAIN_API_KEYS", "").strip())
    if not api_keys_set:
        _log.warning(
            "SECURITY WARNING: Running in dev mode — API is unauthenticated. "
            "Set BRAIN_API_KEYS=key1,key2 to require Bearer token authentication."
        )
    else:
        _log.info("SECURITY: API authentication enabled (%d key(s)).",
                  len([k for k in os.environ.get("BRAIN_API_KEYS", "").split(",") if k.strip()]))

    cors_origins = os.environ.get("BRAIN_CORS_ORIGINS", "*")
    if cors_origins.strip() == "*":
        _log.warning(
            "SECURITY WARNING: CORS allows all origins (*). "
            "Set BRAIN_CORS_ORIGINS=https://yourapp.example.com for production."
        )
    else:
        _log.info("SECURITY: CORS restricted to: %s", cors_origins)

    max_body = int(os.environ.get("BRAIN_MAX_BODY_SIZE", str(1024 * 1024)))
    rate_default = int(os.environ.get("BRAIN_RATE_LIMIT_DEFAULT", "60"))
    rate_expensive = int(os.environ.get("BRAIN_RATE_LIMIT_EXPENSIVE", "10"))
    _log.info(
        "SECURITY: rate_limit=%d/min (LLM-intensive=%d/min), max_body=%d bytes",
        rate_default, rate_expensive, max_body,
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Called once at startup. The Brain singleton is stored on ``app.state.brain``
    and retrieved per-request via the ``get_brain`` dependency.

    All routes are mounted under the ``/v1`` prefix for API versioning.
    """
    app = FastAPI(
        title="Agent Brain API",
        description=(
            "Self-learning memory layer for AI agent frameworks. "
            "Provides learn, recall, evaluate, compose, and feedback endpoints."
        ),
        version="0.5.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # Security middleware
    # Order matters: middleware is applied LIFO (last added = outermost).
    # Stack (outermost → innermost): CORS → SecurityHeaders → BodySize → RateLimit → routes
    # ------------------------------------------------------------------
    from agent_brain.api.middleware import (
        BodySizeLimitMiddleware,
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )

    cors_origins_raw = os.environ.get("BRAIN_CORS_ORIGINS", "*")
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    # SecurityHeaders added after CORS so headers appear on all responses
    app.add_middleware(SecurityHeadersMiddleware)

    max_body = int(os.environ.get("BRAIN_MAX_BODY_SIZE", str(1024 * 1024)))
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=max_body)

    rate_default = int(os.environ.get("BRAIN_RATE_LIMIT_DEFAULT", "60"))
    rate_expensive = int(os.environ.get("BRAIN_RATE_LIMIT_EXPENSIVE", "10"))
    app.add_middleware(RateLimitMiddleware, default_limit=rate_default, expensive_limit=rate_expensive)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(BrainValidationError)
    async def brain_validation_error_handler(
        request: Request, exc: BrainValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # ------------------------------------------------------------------
    # Brain instance
    # ------------------------------------------------------------------
    storage = _make_storage()
    embeddings = _make_embeddings()
    llm = _make_llm()

    app.state.brain = Brain(
        embeddings=embeddings,
        storage=storage,
        llm=llm,
    )

    # ------------------------------------------------------------------
    # API v1 routes
    # ------------------------------------------------------------------
    app.include_router(router, prefix="/v1")

    # ------------------------------------------------------------------
    # Startup security diagnostics
    # ------------------------------------------------------------------
    _log_security_config()

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
