"""Security middleware for the Agent Brain API.

Three Starlette BaseHTTPMiddleware components:

SecurityHeadersMiddleware
    Adds defensive HTTP headers to every response.

RateLimitMiddleware
    Per-IP, per-path fixed-window rate limiter (in-memory, single-process).
    LLM-intensive paths (/v1/evaluate, /v1/compose, /v1/evolve) use a lower
    limit to prevent accidental or abusive LLM cost spikes.
    Configure via env vars:
        BRAIN_RATE_LIMIT_DEFAULT   (default 60 req/min)
        BRAIN_RATE_LIMIT_EXPENSIVE (default 10 req/min)

BodySizeLimitMiddleware
    Rejects requests whose Content-Length header exceeds the configured max.
    Configure via env var:
        BRAIN_MAX_BODY_SIZE (bytes, default 1 048 576 = 1 MB)
"""

import logging
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_log = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add defensive security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP, per-path fixed-window rate limiter.

    Uses one-minute windows keyed on (client_ip, request_path, window_index).
    LLM-intensive paths are rate-limited more aggressively.

    Args:
        default_limit: Max requests per minute for regular paths.
        expensive_limit: Max requests per minute for LLM-intensive paths.
    """

    # Paths that trigger multiple LLM calls — apply the tighter limit.
    _EXPENSIVE_PATH_FRAGMENTS = ("/evaluate", "/compose", "/evolve")

    def __init__(
        self,
        app,
        default_limit: int = 60,
        expensive_limit: int = 10,
    ) -> None:
        super().__init__(app)
        self._default = default_limit
        self._expensive = expensive_limit
        self._lock = threading.Lock()
        # (client_ip, path, window_minute) -> request_count
        self._counts: dict[tuple, int] = {}
        self._last_gc = time.time()

    def _get_limit(self, path: str) -> int:
        for fragment in self._EXPENSIVE_PATH_FRAGMENTS:
            if fragment in path:
                return self._expensive
        return self._default

    def _gc(self) -> None:
        """Remove counters from previous windows to prevent unbounded growth."""
        cutoff = int(time.time() / 60) - 1
        self._counts = {k: v for k, v in self._counts.items() if k[2] >= cutoff}

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        window = int(time.time() / 60)
        limit = self._get_limit(path)
        key = (ip, path, window)

        with self._lock:
            now = time.time()
            if now - self._last_gc > 300:  # GC every 5 minutes
                self._gc()
                self._last_gc = now
            self._counts[key] = self._counts.get(key, 0) + 1
            count = self._counts[key]

        if count > limit:
            _log.warning(
                "Rate limit exceeded: ip=%s path=%s count=%d limit=%d",
                ip, path, count, limit,
            )
            from agent_brain.api.audit import AuditEvent, log_event  # deferred to avoid circular import
            log_event(AuditEvent.RATE_LIMITED, ip=ip, path=path, count=count, limit=limit)
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Max {limit} requests per minute."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured maximum.

    Only inspects the Content-Length header — does not buffer the body.
    Requests without a Content-Length header are not rejected (chunked transfer
    encoding is accepted; application-level limits on field length still apply).

    Args:
        max_body_size: Maximum allowed body size in bytes (default 1 MB).
    """

    _DEFAULT_MAX = 1 * 1024 * 1024  # 1 MB

    def __init__(self, app, max_body_size: int = _DEFAULT_MAX) -> None:
        super().__init__(app)
        self._max = max_body_size

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("Content-Length")
        if cl:
            try:
                size = int(cl)
                if size > self._max:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Request body too large. "
                                f"Maximum allowed: {self._max} bytes."
                            )
                        },
                    )
            except ValueError:
                pass  # Malformed Content-Length — let FastAPI handle it
        return await call_next(request)
