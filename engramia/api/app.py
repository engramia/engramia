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
    ENGRAMIA_RATE_LIMIT_PER_KEY total requests/min per API key across all paths (default: 120)
    ENGRAMIA_MAX_BODY_SIZE      max request body in bytes (default: 1048576 = 1MB)
    ENGRAMIA_ALLOW_NO_AUTH      required when ENGRAMIA_AUTH_MODE=dev
    ENGRAMIA_LLM_CONCURRENCY    max parallel LLM provider calls (default: 10)

Run:
    uvicorn engramia.api.app:create_app --factory
    # or with docker compose up
"""

import logging
import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engramia import Memory, __version__
from engramia._factory import make_embeddings, make_llm, make_storage
from engramia.api.analytics import router as analytics_router
from engramia.api.cloud_auth import router as cloud_auth_router
from engramia.api.errors import STATUS_TO_ERROR_CODE, ErrorCode
from engramia.api.governance import router as governance_router
from engramia.api.jobs import router as jobs_router
from engramia.api.keys import router as keys_router
from engramia.api.routes import meta_router, router
from engramia.billing.webhooks import router as billing_router
from engramia.exceptions import (
    AuthorizationError,
    EngramiaError,
    ProviderError,
    QuotaExceededError,
    StorageError,
    ValidationError,
)

_log = logging.getLogger(__name__)


def _log_security_config() -> None:
    """Emit startup warnings for insecure defaults."""
    auth_mode = os.environ.get("ENGRAMIA_AUTH_MODE", "auto").lower()
    db_url_set = bool(os.environ.get("ENGRAMIA_DATABASE_URL", "").strip())
    api_keys_set = bool(os.environ.get("ENGRAMIA_API_KEYS", "").strip())

    if auth_mode == "dev":
        env = os.environ.get("ENGRAMIA_ENVIRONMENT", "").lower().strip()
        if env not in ("", "local", "test", "development"):
            _log.critical(
                "FATAL: ENGRAMIA_AUTH_MODE=dev is not permitted in environment %r. "
                "This would expose the entire API without authentication. "
                "Set ENGRAMIA_AUTH_MODE=db or ENGRAMIA_AUTH_MODE=env for non-local environments.",
                env,
            )
            sys.exit(1)
        _log.warning(
            "SECURITY WARNING: Running in dev mode — API is unauthenticated. "
            "Never use ENGRAMIA_AUTH_MODE=dev in production."
        )
    elif auth_mode in ("db", "auto") and db_url_set:
        _log.info("SECURITY: DB auth enabled (ENGRAMIA_AUTH_MODE=%s).", auth_mode)
    elif api_keys_set:
        env_role = os.environ.get("ENGRAMIA_ENV_AUTH_ROLE", "owner").lower()
        _log.info("SECURITY: Env-var auth enabled (ENGRAMIA_API_KEYS), role=%s.", env_role)
        if env_role == "owner":
            _log.warning(
                "SECURITY: ENGRAMIA_ENV_AUTH_ROLE=owner — all API key holders have full access. "
                "Set ENGRAMIA_ENV_AUTH_ROLE=editor|admin for multi-user deployments."
            )
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
    rate_per_key = int(os.environ.get("ENGRAMIA_RATE_LIMIT_PER_KEY", "120"))
    _log.info(
        "SECURITY: rate_limit=%d/min (LLM-intensive=%d/min, per-key=%d/min), max_body=%d bytes",
        rate_default,
        rate_expensive,
        rate_per_key,
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


def _recover_orphaned_jobs(engine) -> None:
    """Reset 'running' jobs that were interrupted by a crash to 'pending'.

    Called at startup with the job engine. Any job that has been in 'running'
    state for more than 10 minutes is treated as orphaned and reset so the
    worker can retry it.
    """
    import time

    from sqlalchemy import text

    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 600))
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE jobs SET status = 'pending', started_at = NULL "
                    "WHERE status = 'running' AND started_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
        if result.rowcount:
            _log.warning(
                "Crash recovery: reset %d orphaned 'running' job(s) to 'pending'.",
                result.rowcount,
            )
    except Exception as exc:
        _log.warning("Crash recovery query failed (non-fatal): %s", exc)


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

    # Swagger UI and OpenAPI schema are only exposed in dev/staging environments.
    # In production (default when ENGRAMIA_ENV is unset), these endpoints return 404
    # to reduce attack surface and avoid leaking API schema to the public internet.
    _is_dev = os.getenv("ENGRAMIA_ENV", "prod").lower() in ("dev", "development", "local", "staging")

    app = FastAPI(
        title="Engramia API",
        description=(
            "Reusable execution memory and evaluation infrastructure for AI agent frameworks. "
            "Provides learn, recall, evaluate, compose, and feedback endpoints."
        ),
        version=__version__,
        docs_url="/docs" if _is_dev else None,
        redoc_url="/redoc" if _is_dev else None,
        openapi_url="/openapi.json" if _is_dev else None,
    )

    # ------------------------------------------------------------------
    # Security middleware
    # Order matters: middleware is applied LIFO (last added = outermost).
    # Stack (outermost → innermost):
    #   CORS → RequestID → Timing → SecurityHeaders → BodySize → RateLimit → routes
    # ------------------------------------------------------------------
    from engramia.api.middleware import (
        BodySizeLimitMiddleware,
        MaintenanceModeMiddleware,
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
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    app.add_middleware(MaintenanceModeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    # Telemetry middleware (innermost of the outer stack so request_id is
    # available to all handlers; timing wraps the actual route dispatch).
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    max_body = int(os.environ.get("ENGRAMIA_MAX_BODY_SIZE", str(1024 * 1024)))
    app.add_middleware(BodySizeLimitMiddleware, max_body_size=max_body)

    rate_default = int(os.environ.get("ENGRAMIA_RATE_LIMIT_DEFAULT", "60"))
    rate_expensive = int(os.environ.get("ENGRAMIA_RATE_LIMIT_EXPENSIVE", "10"))
    rate_per_key = int(os.environ.get("ENGRAMIA_RATE_LIMIT_PER_KEY", "120"))
    app.add_middleware(
        RateLimitMiddleware,
        default_limit=rate_default,
        expensive_limit=rate_expensive,
        key_limit=rate_per_key,
    )

    # ------------------------------------------------------------------
    # Error handlers — structured error responses
    #
    # All API errors return a JSON body conforming to ErrorResponse:
    #   error_code    — machine-readable string enum (e.g. "UNAUTHORIZED")
    #   detail        — human-readable description
    #   error_context — optional dict with structured context (limits, etc.)
    # ------------------------------------------------------------------

    _QUOTA_INNER_ERRORS = frozenset(
        {
            "quota_exceeded",
            "project_quota_exceeded",
            "overage_budget_cap_reached",
        }
    )
    # Context keys promoted to error_context for structured consumers.
    _CONTEXT_KEYS = frozenset({"current", "limit", "current_count", "retry_after", "reset_date", "metric", "max_bytes"})

    def _build_error_body(status_code: int, detail) -> dict:
        """Convert an HTTPException detail into a structured ErrorResponse body."""
        default_code = STATUS_TO_ERROR_CODE.get(status_code, ErrorCode.ERROR)

        if isinstance(detail, dict):
            # Explicit error_code in the detail dict takes precedence.
            inner_error_code = detail.get("error_code", "")
            inner_error = detail.get("error", "")
            if inner_error_code:
                error_code = inner_error_code
            elif inner_error in _QUOTA_INNER_ERRORS or (status_code == 429 and "limit" in detail):
                error_code = ErrorCode.QUOTA_EXCEEDED
            else:
                error_code = default_code

            human_msg = detail.get("detail") or detail.get("message") or str(detail)
            context = {k: detail[k] for k in _CONTEXT_KEYS if k in detail}
            body: dict = {"error_code": error_code, "detail": human_msg}
            if context:
                body["error_context"] = context
            return body

        # Plain string or None detail.
        return {
            "error_code": default_code,
            "detail": str(detail) if detail else STATUS_TO_ERROR_CODE.get(status_code, "An error occurred."),
        }

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        body = _build_error_body(exc.status_code, exc.detail)
        headers = getattr(exc, "headers", None) or {}
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        _log.warning("ValueError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=422,
            content={"error_code": ErrorCode.VALIDATION_ERROR, "detail": "Invalid request parameters."},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
        _log.warning("ValidationError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=422,
            content={"error_code": ErrorCode.VALIDATION_ERROR, "detail": "Validation error in request."},
        )

    # ------------------------------------------------------------------
    # EngramiaError subclass handlers — catch domain exceptions that
    # escape route handlers and map them to structured HTTP responses.
    # ------------------------------------------------------------------

    @app.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
        _log.warning("ProviderError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=501,
            content={
                "error_code": ErrorCode.PROVIDER_NOT_CONFIGURED,
                "detail": "LLM or embedding provider not configured.",
            },
        )

    @app.exception_handler(StorageError)
    async def storage_error_handler(request: Request, exc: StorageError) -> JSONResponse:
        _log.error("StorageError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content={"error_code": ErrorCode.STORAGE_ERROR, "detail": "Storage backend error."},
        )

    @app.exception_handler(QuotaExceededError)
    async def quota_exceeded_error_handler(request: Request, exc: QuotaExceededError) -> JSONResponse:
        _log.warning("QuotaExceededError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=429,
            content={"error_code": ErrorCode.QUOTA_EXCEEDED, "detail": "Pattern quota exceeded."},
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        _log.warning("AuthorizationError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=403,
            content={"error_code": ErrorCode.FORBIDDEN, "detail": "Operation not permitted for the current role."},
        )

    @app.exception_handler(EngramiaError)
    async def engramia_error_handler(request: Request, exc: EngramiaError) -> JSONResponse:
        _log.error("Unhandled EngramiaError in request %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"error_code": ErrorCode.INTERNAL_ERROR, "detail": "An internal error occurred."},
        )

    # ------------------------------------------------------------------
    # Memory instance
    # ------------------------------------------------------------------
    storage = make_storage()
    embeddings = make_embeddings()
    if embeddings is None:
        _log.warning(
            "No embedding provider configured — learn() and recall() will return "
            "503 ProviderError. Set ENGRAMIA_EMBEDDING_MODEL and install 'engramia[openai]' "
            "to enable semantic search."
        )
    llm = make_llm()

    # Redaction is enabled by default to protect PII/secrets at rest.
    # Set ENGRAMIA_REDACTION=false to disable (dev/local use only).
    from engramia.governance.redaction import RedactionPipeline

    _redaction_enabled = os.environ.get("ENGRAMIA_REDACTION", "true").lower() not in ("false", "0", "no")
    redaction = RedactionPipeline.default() if _redaction_enabled else None
    if not _redaction_enabled:
        _log.warning(
            "SECURITY: PII/secrets redaction is disabled (ENGRAMIA_REDACTION=false). Do not use this in production."
        )

    app.state.memory = Memory(
        embeddings=embeddings,
        storage=storage,
        llm=llm,
        redaction=redaction,
    )

    # ------------------------------------------------------------------
    # Auth engine (DB auth mode)
    # ------------------------------------------------------------------
    app.state.auth_engine = _make_auth_engine()

    # Load persisted revoked JTIs from DB so revocations survive restarts (M-02).
    from engramia.api.cloud_auth import set_blocklist_engine

    set_blocklist_engine(app.state.auth_engine)

    # ------------------------------------------------------------------
    # Async job service + worker (Phase 5.4)
    # ------------------------------------------------------------------
    from engramia.jobs import JobService, JobWorker

    # Use the storage engine for job queue if Postgres is configured,
    # otherwise use in-memory fallback (suitable for dev/JSON mode).
    job_engine = getattr(storage, "_engine", None)
    job_service = JobService(engine=job_engine, memory=app.state.memory)
    app.state.job_service = job_service

    if job_engine is not None:
        _recover_orphaned_jobs(job_engine)

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
    # Prometheus /metrics endpoint (opt-in via ENGRAMIA_METRICS=true)
    # Exposes Python process metrics + custom Engramia Gauges:
    #   engramia_pattern_count, engramia_avg_eval_score,
    #   engramia_total_runs, engramia_success_rate, engramia_reuse_rate
    # ------------------------------------------------------------------
    if os.environ.get("ENGRAMIA_METRICS", "false").lower() == "true":
        try:
            from engramia.api.prom_metrics import build_metrics_app

            metrics_app = build_metrics_app(app.state.memory)

            # Wrap the metrics ASGI app with a lightweight token guard.
            # Set ENGRAMIA_METRICS_TOKEN to require a Bearer token on /metrics.
            # Without a token configured, /metrics is only safe behind a private
            # network or Caddy access rule.
            _metrics_token = os.environ.get("ENGRAMIA_METRICS_TOKEN", "").strip()

            if _metrics_token:
                import hmac as _hmac

                from starlette.responses import Response as _StarletteResponse

                _expected = _metrics_token.encode()

                async def _guarded_metrics(scope, receive, send):
                    if scope["type"] == "http":
                        headers = dict(scope.get("headers", []))
                        auth = headers.get(b"authorization", b"").decode()
                        token = auth[len("Bearer ") :] if auth.startswith("Bearer ") else ""
                        if not _hmac.compare_digest(token.encode(), _expected):
                            resp = _StarletteResponse(
                                "Unauthorized",
                                status_code=401,
                                media_type="text/plain",
                            )
                            await resp(scope, receive, send)
                            return
                    await metrics_app(scope, receive, send)

                app.mount("/metrics", _guarded_metrics)
                _log.info("Prometheus /metrics endpoint enabled (token-protected).")
            else:
                app.mount("/metrics", metrics_app)
                _log.warning(
                    "SECURITY: Prometheus /metrics is enabled without a token. "
                    "Set ENGRAMIA_METRICS_TOKEN or restrict access via network policy."
                )
        except ImportError:
            _log.warning("prometheus_client not installed — /metrics not mounted.")

    # ------------------------------------------------------------------
    # Billing service (Phase 6) — no-op when DB engine is not available
    # ------------------------------------------------------------------
    from engramia.billing import BillingService

    billing_engine = getattr(storage, "_engine", None) or app.state.auth_engine
    app.state.billing_service = BillingService(engine=billing_engine)
    if billing_engine is not None:
        _log.info("Billing service initialised (DB engine available).")
    else:
        _log.info("Billing service in no-op mode (no DB engine — dev/JSON storage).")

    # ------------------------------------------------------------------
    # Cloud auth routes (no /v1 prefix — web registration flow)
    # ------------------------------------------------------------------
    app.include_router(cloud_auth_router, prefix="/auth", tags=["Cloud Auth"])

    # ------------------------------------------------------------------
    # API v1 routes
    # ------------------------------------------------------------------
    app.include_router(meta_router, prefix="/v1")
    app.include_router(router, prefix="/v1")
    app.include_router(keys_router, prefix="/v1")
    app.include_router(jobs_router, prefix="/v1")
    app.include_router(governance_router, prefix="/v1")
    app.include_router(analytics_router, prefix="/v1")
    app.include_router(billing_router, prefix="/v1")

    # ------------------------------------------------------------------
    # Dashboard static files (Phase 5.3)
    # ------------------------------------------------------------------
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    dashboard_dir = Path(__file__).parent.parent.parent / "dashboard" / "out"
    if dashboard_dir.exists():
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(dashboard_dir), html=True),
            name="dashboard",
        )
        _log.info("Dashboard mounted from %s", dashboard_dir)

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
