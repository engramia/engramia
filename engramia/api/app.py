# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""FastAPI application factory for Engramia.

Configuration is entirely via environment variables:

    ENGRAMIA_STORAGE        json | postgres          (default: json)
    ENGRAMIA_DATA_PATH      ./brain_data             (json only)
    ENGRAMIA_DATABASE_URL   postgresql://...         (postgres only)
    ENGRAMIA_LLM_PROVIDER   openai                   (default: openai)
    ENGRAMIA_LLM_MODEL      gpt-4.1                  (default: gpt-4.1)
    OPENAI_API_KEY       sk-...
    ENGRAMIA_EMBEDDING_MODEL text-embedding-3-small  (default)
    ENGRAMIA_API_KEYS       key1,key2                (empty = dev mode, no auth)
    ENGRAMIA_HOST           0.0.0.0                  (default)
    ENGRAMIA_PORT           8000                     (default)

Security configuration (env vars):
    ENGRAMIA_CORS_ORIGINS       comma-separated allowed origins (default: none — CORS disabled)
    ENGRAMIA_RATE_LIMIT_DEFAULT requests/min for regular endpoints (default: 60)
    ENGRAMIA_RATE_LIMIT_EXPENSIVE requests/min for LLM endpoints (default: 10)
    ENGRAMIA_MAX_BODY_SIZE      max request body in bytes (default: 1048576 = 1MB)

Run:
    uvicorn engramia.api.app:create_app --factory
    # or with docker compose up
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engramia import Memory, __version__
from engramia._factory import make_embeddings, make_llm, make_storage
from engramia.api.routes import router
from engramia.exceptions import ValidationError as BrainValidationError

_log = logging.getLogger(__name__)


def _log_security_config() -> None:
    """Emit startup warnings for insecure defaults."""
    api_keys_set = bool(os.environ.get("ENGRAMIA_API_KEYS", "").strip())
    if not api_keys_set:
        _log.warning(
            "SECURITY WARNING: Running in dev mode — API is unauthenticated. "
            "Set ENGRAMIA_API_KEYS=key1,key2 to require Bearer token authentication."
        )
    else:
        _log.info("SECURITY: API authentication enabled.")

    cors_origins = os.environ.get("ENGRAMIA_CORS_ORIGINS", "")
    if not cors_origins.strip():
        _log.info("SECURITY: CORS disabled (no origins configured).")
    elif cors_origins.strip() == "*":
        _log.warning(
            "SECURITY WARNING: CORS allows all origins (*). "
            "Set ENGRAMIA_CORS_ORIGINS=https://yourapp.example.com for production."
        )
    else:
        _log.info("SECURITY: CORS restricted to configured origins.")

    max_body = int(os.environ.get("ENGRAMIA_MAX_BODY_SIZE", str(1024 * 1024)))
    rate_default = int(os.environ.get("ENGRAMIA_RATE_LIMIT_DEFAULT", "60"))
    rate_expensive = int(os.environ.get("ENGRAMIA_RATE_LIMIT_EXPENSIVE", "10"))
    _log.info(
        "SECURITY: rate_limit=%d/min (LLM-intensive=%d/min), max_body=%d bytes",
        rate_default,
        rate_expensive,
        max_body,
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Called once at startup. The Brain singleton is stored on ``app.state.brain``
    and retrieved per-request via the ``get_brain`` dependency.

    All routes are mounted under the ``/v1`` prefix for API versioning.
    """
    app = FastAPI(
        title="Engramia API",
        description=(
            "Self-learning memory layer for AI agent frameworks. "
            "Provides learn, recall, evaluate, compose, and feedback endpoints."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # Security middleware
    # Order matters: middleware is applied LIFO (last added = outermost).
    # Stack (outermost → innermost): CORS → SecurityHeaders → BodySize → RateLimit → routes
    # ------------------------------------------------------------------
    from engramia.api.middleware import (
        BodySizeLimitMiddleware,
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )

    cors_origins_raw = os.environ.get("ENGRAMIA_CORS_ORIGINS", "")
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    # SecurityHeaders added after CORS so headers appear on all responses
    app.add_middleware(SecurityHeadersMiddleware)

    max_body = int(os.environ.get("ENGRAMIA_MAX_BODY_SIZE", str(1024 * 1024)))
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=max_body)

    rate_default = int(os.environ.get("ENGRAMIA_RATE_LIMIT_DEFAULT", "60"))
    rate_expensive = int(os.environ.get("ENGRAMIA_RATE_LIMIT_EXPENSIVE", "10"))
    app.add_middleware(RateLimitMiddleware, default_limit=rate_default, expensive_limit=rate_expensive)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        _log.warning("ValueError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=422, content={"detail": "Invalid request parameters."})

    @app.exception_handler(BrainValidationError)
    async def brain_validation_error_handler(request: Request, exc: BrainValidationError) -> JSONResponse:
        _log.warning("ValidationError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=422, content={"detail": "Validation error in request."})

    # ------------------------------------------------------------------
    # Brain instance
    # ------------------------------------------------------------------
    storage = make_storage()
    embeddings = make_embeddings()
    llm = make_llm()

    app.state.brain = Memory(
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
        "Engramia API started — storage=%s, llm=%s",
        type(storage).__name__,
        type(llm).__name__ if llm else "None",
    )
    return app


# Module-level app instance for uvicorn / docker.
# Created lazily so that importing this module in tests doesn't
# immediately try to connect to OpenAI / Postgres.
# Uvicorn usage: uvicorn engramia.api.app:create_app --factory
# Or: from engramia.api.app import app  (triggers creation)
try:
    import os

    _skip_auto_create = os.environ.get("ENGRAMIA_SKIP_AUTO_APP", "0") == "1"
except Exception:
    _skip_auto_create = True

if not _skip_auto_create:
    app = create_app()
