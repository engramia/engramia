# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""FastAPI application factory for Engramia.

Configuration is entirely via environment variables:

    ENGRAMIA_STORAGE        json | postgres          (default: json)
    ENGRAMIA_DATA_PATH      ./engramia_data          (json only)
    ENGRAMIA_DATABASE_URL   postgresql://...         (postgres only)
    ENGRAMIA_LLM_PROVIDER   openai                   (default: openai)
    ENGRAMIA_LLM_MODEL      gpt-4.1                  (default: gpt-4.1)
    OPENAI_API_KEY          sk-...
    ENGRAMIA_EMBEDDING_MODEL text-embedding-3-small  (default)
    ENGRAMIA_API_KEYS       key1,key2                (env-var auth mode)
    ENGRAMIA_HOST           0.0.0.0                  (default)
    ENGRAMIA_PORT           8000                     (default)

Authentication (Phase 5.2):
    ENGRAMIA_AUTH_MODE      auto | env | db | dev    (default: auto)
        auto: DB auth if ENGRAMIA_DATABASE_URL set, else env-var keys
        env:  always env-var keys (ENGRAMIA_API_KEYS) — backward compat
        db:   always DB auth (api_keys table) — requires DATABASE_URL
        dev:  no auth (requires ENGRAMIA_ALLOW_NO_AUTH=true)

Security configuration:
    ENGRAMIA_CORS_ORIGINS       comma-separated allowed origins (default: none)
    ENGRAMIA_RATE_LIMIT_DEFAULT requests/min for regular endpoints (default: 60)
    ENGRAMIA_RATE_LIMIT_EXPENSIVE requests/min for LLM endpoints (default: 10)
    ENGRAMIA_MAX_BODY_SIZE      max request body in bytes (default: 1048576 = 1MB)
    ENGRAMIA_ALLOW_NO_AUTH      required when ENGRAMIA_AUTH_MODE=dev

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
from engramia.api.analytics import router as analytics_router
from engramia.api.governance import router as governance_router
from engramia.api.jobs import router as jobs_router
from engramia.api.keys import router as keys_router
from engramia.api.routes import router
from engramia.exceptions import ValidationError

_log = logging.getLogger(__name__)


def _log_security_config() -> None:
    """Emit startup warnings for insecure defaults."""
    auth_mode = os.environ.get("ENGRAMIA_AUTH_MODE", "auto").lower()
    db_url_set = bool(os.environ.get("ENGRAMIA_DATABASE_URL", "").strip())
    api_keys_set = bool(os.environ.get("ENGRAMIA_API_KEYS", "").strip())

    if auth_mode == "dev":
        _log.warning(
            "SECURITY WARNING: Running in dev mode — API is unauthenticated. "
            "Never use ENGRAMIA_AUTH_MODE=dev in production."
        )
    elif auth_mode in ("db", "auto") and db_url_set:
        _log.info("SECURITY: DB auth enabled (ENGRAMIA_AUTH_MODE=%s).", auth_mode)
    elif api_keys_set:
        _log.info("SECURITY: Env-var auth enabled (ENGRAMIA_API_KEYS).")
    else:
        _log.warning(
            "SECURITY WARNING: No auth configured — API is unauthenticated. "
            "Set ENGRAMIA_API_KEYS or configure DB auth for production."
        )

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


def _make_auth_engine():
    """Create a lightweight SQLAlchemy engine for auth (api_keys lookups).

    Separate from the storage engine so that auth works even when
    ENGRAMIA_STORAGE=json. Returns None if DATABASE_URL is not set or
    if db auth is not applicable for the current AUTH_MODE.
    """
    auth_mode = os.environ.get("ENGRAMIA_AUTH_MODE", "auto").lower()
    if auth_mode == "env":
        return None  # env-var auth only — no DB needed

    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        return None  # no DB configured

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import QueuePool

        engine = create_engine(
            db_url,
            poolclass=QueuePool,
            pool_size=3,
            max_overflow=5,
            pool_pre_ping=True,
        )
        _log.info("Auth engine connected for DB auth.")
        return engine
    except Exception as exc:
        _log.error("Failed to create auth engine: %s", exc)
        return None


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Called once at startup. The Memory singleton is stored on ``app.state.memory``
    and the auth engine (when DB auth is configured) on ``app.state.auth_engine``.

    All core routes are mounted under ``/v1``.
    Key management routes are mounted under ``/v1/keys``.
    """
    # ------------------------------------------------------------------
    # Telemetry (Phase 5.5) — must be first so logging is structured
    # from the very first line of startup output.
    # ------------------------------------------------------------------
    from engramia.telemetry import setup_telemetry
    setup_telemetry()

    app = FastAPI(
        title="Engramia API",
        description=(
            "Reusable execution memory and evaluation infrastructure for AI agent frameworks. "
            "Provides learn, recall, evaluate, compose, and feedback endpoints."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # Security middleware
    # Order matters: middleware is applied LIFO (last added = outermost).
    # Stack (outermost → innermost):
    #   CORS → RequestID → Timing → SecurityHeaders → BodySize → RateLimit → routes
    # ------------------------------------------------------------------
    from engramia.api.middleware import (
        BodySizeLimitMiddleware,
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )
    from engramia.telemetry.middleware import RequestIDMiddleware, TimingMiddleware

    cors_origins_raw = os.environ.get("ENGRAMIA_CORS_ORIGINS", "")
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    # Telemetry middleware (innermost of the outer stack so request_id is
    # available to all handlers; timing wraps the actual route dispatch).
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

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

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
        _log.warning("ValidationError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=422, content={"detail": "Validation error in request."})

    # ------------------------------------------------------------------
    # Memory instance
    # ------------------------------------------------------------------
    storage = make_storage()
    embeddings = make_embeddings()
    llm = make_llm()

    app.state.memory = Memory(
        embeddings=embeddings,
        storage=storage,
        llm=llm,
    )

    # ------------------------------------------------------------------
    # Auth engine (DB auth mode)
    # ------------------------------------------------------------------
    app.state.auth_engine = _make_auth_engine()

    # ------------------------------------------------------------------
    # Async job service + worker (Phase 5.4)
    # ------------------------------------------------------------------
    from engramia.jobs import JobService, JobWorker

    # Use the storage engine for job queue if Postgres is configured,
    # otherwise use in-memory fallback (suitable for dev/JSON mode).
    job_engine = getattr(storage, "_engine", None)
    job_service = JobService(engine=job_engine, memory=app.state.memory)
    app.state.job_service = job_service

    worker = JobWorker(
        service=job_service,
        poll_interval=float(os.environ.get("ENGRAMIA_JOB_POLL_INTERVAL", "2.0")),
        max_concurrent=int(os.environ.get("ENGRAMIA_JOB_MAX_CONCURRENT", "3")),
    )
    app.state.job_worker = worker
    worker.start()

    @app.on_event("shutdown")
    def _stop_job_worker():
        worker.stop()

    # ------------------------------------------------------------------
    # Prometheus /metrics endpoint (Phase 5.5, opt-in)
    # ------------------------------------------------------------------
    if os.environ.get("ENGRAMIA_METRICS", "false").lower() == "true":
        try:
            from prometheus_client import make_asgi_app as _make_prom_app

            metrics_app = _make_prom_app()
            app.mount("/metrics", metrics_app)
            _log.info("Prometheus /metrics endpoint enabled.")
        except ImportError:
            _log.warning("prometheus_client not installed — /metrics not mounted.")

    # ------------------------------------------------------------------
    # API v1 routes
    # ------------------------------------------------------------------
    app.include_router(router, prefix="/v1")
    app.include_router(keys_router, prefix="/v1")
    app.include_router(jobs_router, prefix="/v1")
    app.include_router(governance_router, prefix="/v1")
    app.include_router(analytics_router, prefix="/v1")

    # ------------------------------------------------------------------
    # Startup security diagnostics
    # ------------------------------------------------------------------
    _log_security_config()

    _log.info(
        "Engramia API started — storage=%s, auth_engine=%s, llm=%s",
        type(storage).__name__,
        "configured" if app.state.auth_engine else "none",
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
