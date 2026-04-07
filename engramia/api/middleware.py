# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Security middleware for the Engramia API.

Three Starlette BaseHTTPMiddleware components:

SecurityHeadersMiddleware
    Adds defensive HTTP headers to every response.

RateLimitMiddleware
    Per-IP, per-path AND per-API-key fixed-window rate limiter (in-memory,
    single-process).
    LLM-intensive paths (/v1/evaluate, /v1/compose, /v1/evolve) use a lower
    limit to prevent accidental or abusive LLM cost spikes.
    Configure via env vars:
        ENGRAMIA_RATE_LIMIT_DEFAULT   (default 60 req/min per IP per path)
        ENGRAMIA_RATE_LIMIT_EXPENSIVE (default 10 req/min per IP per path)
        ENGRAMIA_RATE_LIMIT_PER_KEY   (default 120 req/min total per API key)

BodySizeLimitMiddleware
    Rejects requests whose Content-Length header exceeds the configured max.
    Configure via env var:
        ENGRAMIA_MAX_BODY_SIZE (bytes, default 1 048 576 = 1 MB)
"""

import hashlib
import logging
import os
import threading
import time
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_log = logging.getLogger(__name__)


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """Return 503 on all non-health endpoints when ENGRAMIA_MAINTENANCE is set.

    Set ``ENGRAMIA_MAINTENANCE=true`` (or ``1``) to activate. The
    ``/v1/health`` and ``/v1/health/deep`` endpoints remain available so that
    load-balancer health checks continue to work.
    """

    _HEALTH_PATHS: ClassVar[set[str]] = {"/v1/health", "/v1/health/deep"}

    async def dispatch(self, request: Request, call_next):
        if (
            os.environ.get("ENGRAMIA_MAINTENANCE", "").lower() in ("1", "true", "yes")
            and request.url.path not in self._HEALTH_PATHS
        ):
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "SERVICE_UNAVAILABLE",
                    "error_message": "Service is under scheduled maintenance. Please try again later.",
                    "retry_after": 3600,
                },
                headers={"Retry-After": "3600"},
            )
        return await call_next(request)


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
    """Per-IP, per-path and per-API-key fixed-window rate limiter.

    Uses one-minute windows. Two independent buckets per request:
    - IP bucket: keyed on (client_ip, request_path, window_minute)
    - Key bucket: keyed on ("key", sha256(bearer_token)[:32], window_minute)

    LLM-intensive paths are rate-limited more aggressively on the IP bucket.
    The key bucket applies a single total limit across all paths.

    Args:
        default_limit: Max requests per minute per IP for regular paths.
        expensive_limit: Max requests per minute per IP for LLM-intensive paths.
        key_limit: Max total requests per minute per API key (all paths).
    """

    # Paths that trigger multiple LLM calls — apply the tighter limit.
    _EXPENSIVE_PATH_FRAGMENTS = ("/evaluate", "/compose", "/evolve")

    def __init__(
        self,
        app,
        default_limit: int = 60,
        expensive_limit: int = 10,
        key_limit: int = 120,
    ) -> None:
        super().__init__(app)
        self._default = default_limit
        self._expensive = expensive_limit
        self._key_limit = key_limit
        self._lock = threading.Lock()
        # (client_ip, path, window_minute) | ("key", token_hash, window_minute) -> request_count
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
        ip_limit = self._get_limit(path)
        ip_bucket = (ip, path, window)

        # Per-API-key bucket — key is a hash of the raw Bearer token so no
        # plaintext secret is kept in memory. No DB lookup required.
        key_bucket: tuple | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token_hash = hashlib.sha256(auth_header[7:].encode()).hexdigest()[:32]
            key_bucket = ("key", token_hash, window)

        with self._lock:
            now = time.time()
            if now - self._last_gc > 300:  # GC every 5 minutes
                self._gc()
                self._last_gc = now
            self._counts[ip_bucket] = self._counts.get(ip_bucket, 0) + 1
            ip_count = self._counts[ip_bucket]
            key_count = 0
            if key_bucket is not None:
                self._counts[key_bucket] = self._counts.get(key_bucket, 0) + 1
                key_count = self._counts[key_bucket]

        from engramia.api.audit import AuditEvent, log_event  # deferred to avoid circular import

        if ip_count > ip_limit:
            _log.warning(
                "Rate limit exceeded (ip): ip=%s path=%s count=%d limit=%d",
                ip,
                path,
                ip_count,
                ip_limit,
            )
            log_event(AuditEvent.RATE_LIMITED, ip=ip, path=path, count=ip_count, limit=ip_limit)
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMITED",
                    "error_message": f"Rate limit exceeded. Max {ip_limit} requests per minute.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )

        if key_bucket is not None and key_count > self._key_limit:
            _log.warning(
                "Rate limit exceeded (key): path=%s count=%d limit=%d",
                path,
                key_count,
                self._key_limit,
            )
            log_event(AuditEvent.RATE_LIMITED, ip=ip, path=path, count=key_count, limit=self._key_limit)
            return JSONResponse(
                status_code=429,
                content={
                    "error_code": "RATE_LIMITED",
                    "error_message": f"Rate limit exceeded. Max {self._key_limit} requests per minute per API key.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds the configured maximum.

    Inspects the Content-Length header for a fast rejection path. For chunked
    transfer encoding (no Content-Length header), wraps the ASGI receive
    channel and accumulates byte counts — the request is aborted as soon as
    the running total exceeds the limit without buffering the full body.

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
                            "error_code": "PAYLOAD_TOO_LARGE",
                            "error_message": f"Request body too large. Maximum allowed: {self._max} bytes.",
                            "max_bytes": self._max,
                        },
                    )
            except ValueError:
                pass  # Malformed Content-Length — let FastAPI handle it
        else:
            # Chunked / no Content-Length — cap via streaming receive wrapper
            max_size = self._max
            original_receive = request._receive
            bytes_read = 0

            async def capped_receive():
                nonlocal bytes_read
                message = await original_receive()
                if message.get("type") == "http.request":
                    bytes_read += len(message.get("body", b""))
                    if bytes_read > max_size:
                        _log.warning(
                            "Chunked body exceeded limit: %d > %d bytes",
                            bytes_read,
                            max_size,
                        )
                        return {
                            "type": "http.disconnect",
                        }
                return message

            request._receive = capped_receive

        return await call_next(request)
