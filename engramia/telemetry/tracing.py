# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""OpenTelemetry tracing setup and instrumentation helpers.

All OTEL imports are guarded — when the ``telemetry`` extra is not installed
every public function is a no-op so the rest of the codebase can import this
module unconditionally.

Configuration (env vars):
    ENGRAMIA_TELEMETRY          true | false  (default: false)
    ENGRAMIA_OTEL_ENDPOINT      OTLP gRPC endpoint (default: http://localhost:4317)
    ENGRAMIA_OTEL_SERVICE_NAME  service.name attribute (default: engramia-api)
"""

from __future__ import annotations

import functools
import logging
import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_tracer_provider = None
_enabled: bool = False


def is_enabled() -> bool:
    """Return True if OTEL tracing has been successfully initialised."""
    return _enabled


def init_tracing(
    service_name: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Initialise the OpenTelemetry TracerProvider with an OTLP gRPC exporter.

    No-op (with a warning) if the ``opentelemetry-sdk`` package is not installed.

    Args:
        service_name: Value for the ``service.name`` resource attribute.
        endpoint: OTLP gRPC collector endpoint URL.
    """
    global _tracer_provider, _enabled

    svc = service_name or os.environ.get("ENGRAMIA_OTEL_SERVICE_NAME", "engramia-api")
    ep = endpoint or os.environ.get("ENGRAMIA_OTEL_ENDPOINT", "http://localhost:4317")

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        _log.warning(
            "opentelemetry-sdk not installed — tracing disabled. Install with: pip install engramia[telemetry]"
        )
        return

    resource = Resource.create({"service.name": svc})
    provider = TracerProvider(resource=resource)
    insecure = os.environ.get("OTEL_EXPORTER_OTLP_INSECURE", "false").lower() in ("1", "true", "yes")
    exporter = OTLPSpanExporter(endpoint=ep, insecure=insecure)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    _enabled = True
    _log.info("OpenTelemetry tracing enabled — service=%s endpoint=%s", svc, ep)


def get_tracer(name: str = "engramia"):
    """Return an OpenTelemetry Tracer (or a no-op object when OTEL is unavailable).

    Args:
        name: Instrumentation scope name (typically module name).
    """
    if not _enabled:
        return _NoOpTracer()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoOpTracer()


# ---------------------------------------------------------------------------
# @traced decorator
# ---------------------------------------------------------------------------


def traced(span_name: str, attributes: dict[str, Any] | None = None):
    """Decorator that wraps a function in an OpenTelemetry span.

    Records the ``request_id`` contextvar as a span attribute automatically.
    Records exceptions as span events and re-raises them.
    Falls back to a simple latency log when OTEL is not enabled.

    Args:
        span_name: Name of the span (e.g. ``"llm.call"``).
        attributes: Static span attributes to attach.

    Example::

        @traced("llm.call", {"llm.provider": "openai"})
        def call(self, prompt, ...): ...
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            from engramia.telemetry.context import get_request_id

            if not _enabled:
                # Still record latency via a simple log
                start = time.perf_counter()
                try:
                    return fn(*args, **kwargs)
                finally:
                    elapsed = (time.perf_counter() - start) * 1000
                    _log.debug("%.1f ms  %s  request_id=%s", elapsed, span_name, get_request_id())
            else:
                try:
                    from opentelemetry.trace import Status, StatusCode
                except ImportError:
                    return fn(*args, **kwargs)

                tracer = get_tracer(fn.__module__ or "engramia")
                with tracer.start_as_current_span(span_name) as span:
                    rid = get_request_id()
                    if rid:
                        span.set_attribute("engramia.request_id", rid)
                    if attributes:
                        for k, v in attributes.items():
                            span.set_attribute(k, v)
                    start = time.perf_counter()
                    try:
                        result = fn(*args, **kwargs)
                        elapsed = (time.perf_counter() - start) * 1000
                        span.set_attribute("engramia.duration_ms", round(elapsed, 2))
                        return result
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        raise

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# No-op tracer for when OTEL is unavailable
# ---------------------------------------------------------------------------


class _NoOpSpan:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def set_attribute(self, *_):
        pass

    def record_exception(self, *_):
        pass

    def set_status(self, *_):
        pass


class _NoOpTracer:
    def start_as_current_span(self, name: str, **_):
        return _NoOpSpan()
