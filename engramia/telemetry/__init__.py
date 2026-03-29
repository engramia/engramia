# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia observability layer — Phase 5.5.

Entry point: call ``setup_telemetry()`` once at application startup
(inside ``create_app()`` in ``engramia/api/app.py``).

Sub-modules
-----------
context     request_id contextvar
tracing     OpenTelemetry TracerProvider + @traced decorator
metrics     Prometheus counters / histograms
logging     JSON structured log formatter
middleware  RequestIDMiddleware + TimingMiddleware
health      Deep health check probes

Environment variables
---------------------
ENGRAMIA_TELEMETRY          true | false   Enable OTEL tracing (default: false)
ENGRAMIA_OTEL_ENDPOINT      OTLP gRPC collector URL (default: http://localhost:4317)
ENGRAMIA_OTEL_SERVICE_NAME  service.name attribute (default: engramia-api)
ENGRAMIA_JSON_LOGS          true | false   Enable JSON logging (default: false)
ENGRAMIA_METRICS            true | false   Enable Prometheus /metrics (default: false)
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def setup_telemetry() -> None:
    """Initialise all enabled observability features from env vars.

    Safe to call multiple times — each sub-system is idempotent.
    Called once from ``engramia.api.app.create_app()`` at startup.
    """
    _setup_json_logging()
    _setup_tracing()
    _setup_metrics()


def _setup_json_logging() -> None:
    if os.environ.get("ENGRAMIA_JSON_LOGS", "false").lower() == "true":
        try:
            from engramia.telemetry.logging import configure_json_logging
            configure_json_logging()
        except Exception as exc:
            _log.warning("Failed to configure JSON logging: %s", exc)


def _setup_tracing() -> None:
    if os.environ.get("ENGRAMIA_TELEMETRY", "false").lower() == "true":
        try:
            from engramia.telemetry.tracing import init_tracing
            init_tracing()
        except Exception as exc:
            _log.warning("Failed to initialise OpenTelemetry tracing: %s", exc)


def _setup_metrics() -> None:
    if os.environ.get("ENGRAMIA_METRICS", "false").lower() == "true":
        try:
            from engramia.telemetry.metrics import init_metrics
            init_metrics()
        except Exception as exc:
            _log.warning("Failed to initialise Prometheus metrics: %s", exc)
