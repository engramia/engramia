# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Request ID and timing middleware for the Engramia API.

RequestIDMiddleware
    Reads ``X-Request-ID`` from the incoming request (or generates a UUID4).
    Stores the ID in the ``engramia_request_id`` contextvar and echoes it back
    via the ``X-Request-ID`` response header.

TimingMiddleware
    Wraps every request in a perf_counter measurement, logs the result as a
    structured message, and records a Prometheus observation (when enabled).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from starlette.requests import Request

_log = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate a request ID for every HTTP request.

    The request ID is:
    1. Read from the ``X-Request-ID`` header if present (caller-supplied).
    2. Generated as a UUID4 otherwise.

    The ID is stored in the ``engramia_request_id`` contextvar so it is
    available throughout the request lifecycle (routes, providers, jobs).
    It is also echoed back in the ``X-Request-ID`` response header.
    """

    async def dispatch(self, request: Request, call_next):
        from engramia.telemetry.context import reset_request_id, set_request_id

        incoming = request.headers.get("X-Request-ID", "").strip()
        rid = incoming if incoming else str(uuid.uuid4())

        request.state.request_id = rid
        token = set_request_id(rid)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)

        response.headers["X-Request-ID"] = rid
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Measure and log per-request latency; record Prometheus histogram.

    Logs at DEBUG level for 2xx/3xx, WARNING for 4xx/5xx.
    Path normalisation strips UUIDs so ``/v1/jobs/abc-123`` becomes
    ``/v1/jobs/{id}`` in metric labels (cardinality control).
    """

    # Paths to skip timing for (typically healthcheck probes)
    _SKIP_PATHS: frozenset[str] = frozenset({"/v1/health", "/metrics"})

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        start = time.perf_counter()
        response = await call_next(request)
        duration_s = time.perf_counter() - start

        if path in self._SKIP_PATHS:
            return response

        status = response.status_code
        rid = getattr(request.state, "request_id", "")
        level = logging.WARNING if status >= 400 else logging.DEBUG
        _log.log(
            level,
            "%s %s %d %.1fms request_id=%s",
            method,
            path,
            status,
            duration_s * 1000,
            rid,
        )

        # Prometheus observation (no-op when metrics are disabled)
        try:
            from engramia.telemetry.metrics import observe_request
            observe_request(method, _normalise_path(path), status, duration_s)
        except Exception:
            pass

        return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re  # noqa: E402

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _normalise_path(path: str) -> str:
    """Replace UUID segments with ``{id}`` for low-cardinality metric labels."""
    return _UUID_RE.sub("{id}", path)
