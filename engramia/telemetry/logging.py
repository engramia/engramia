# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Structured JSON log formatter with trace-context injection.

When enabled (ENGRAMIA_JSON_LOGS=true), replaces the root handler's formatter
with a JSON formatter that automatically injects:
  - ``request_id``  from engramia.telemetry.context
  - ``trace_id``    from the active OpenTelemetry span (if present)
  - ``span_id``     from the active OpenTelemetry span (if present)
  - ``tenant_id``   from engramia._context (scope contextvar)
  - ``project_id``  from engramia._context (scope contextvar)

All injections are guarded — no import failure can break logging.

Configuration:
    ENGRAMIA_JSON_LOGS    true | false  (default: false)
"""

from __future__ import annotations

import logging


class _ContextInjectingFormatter(logging.Formatter):
    """Formatter that adds trace + request context fields to every record."""

    def format(self, record: logging.LogRecord) -> str:
        # Inject request_id
        try:
            from engramia.telemetry.context import get_request_id

            record.__dict__.setdefault("request_id", get_request_id() or "")
        except Exception:
            record.__dict__.setdefault("request_id", "")

        # Inject OTEL trace/span IDs
        try:
            from opentelemetry import trace

            span = trace.get_current_span()  # type: ignore[attr-defined]
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                record.__dict__.setdefault("trace_id", format(ctx.trace_id, "032x"))
                record.__dict__.setdefault("span_id", format(ctx.span_id, "016x"))
            else:
                record.__dict__.setdefault("trace_id", "")
                record.__dict__.setdefault("span_id", "")
        except Exception:
            record.__dict__.setdefault("trace_id", "")
            record.__dict__.setdefault("span_id", "")

        # Inject tenant/project from scope contextvar
        try:
            from engramia._context import get_scope

            scope = get_scope()
            record.__dict__.setdefault("tenant_id", scope.tenant_id)
            record.__dict__.setdefault("project_id", scope.project_id)
        except Exception:
            record.__dict__.setdefault("tenant_id", "")
            record.__dict__.setdefault("project_id", "")

        return super().format(record)


def configure_json_logging() -> None:
    """Replace the root logger's handler formatter with a JSON formatter.

    No-op (with a warning) if ``python-json-logger`` is not installed.
    Called once at application startup when ENGRAMIA_JSON_LOGS=true.
    """
    try:
        from pythonjsonlogger.jsonlogger import JsonFormatter

        class _EngramiaJsonFormatter(_ContextInjectingFormatter, JsonFormatter):
            pass

        fmt = _EngramiaJsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(request_id)s %(trace_id)s %(span_id)s %(tenant_id)s %(project_id)s"
        )

        root = logging.getLogger()
        if root.handlers:
            root.handlers[0].setFormatter(fmt)
        else:
            handler = logging.StreamHandler()
            handler.setFormatter(fmt)
            root.addHandler(handler)

        logging.getLogger(__name__).info("JSON structured logging enabled.")
    except ImportError:
        logging.getLogger(__name__).warning(
            "python-json-logger not installed — JSON logging disabled. Install with: pip install engramia[telemetry]"
        )
