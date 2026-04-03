# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia/telemetry/logging.py."""

import logging
import sys
from unittest.mock import patch


class TestContextInjectingFormatter:
    def _make_record(self, msg="test message"):
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_injects_request_id_field(self):
        from engramia.telemetry.logging import _ContextInjectingFormatter
        from engramia.telemetry.context import reset_request_id, set_request_id

        fmt = _ContextInjectingFormatter("%(message)s")
        token = set_request_id("req-abc")
        try:
            record = self._make_record()
            fmt.format(record)
            assert record.__dict__.get("request_id") == "req-abc"
        finally:
            reset_request_id(token)

    def test_injects_empty_request_id_when_unset(self):
        from engramia.telemetry.logging import _ContextInjectingFormatter
        from engramia.telemetry.context import get_request_id

        fmt = _ContextInjectingFormatter("%(message)s")
        record = self._make_record()
        fmt.format(record)
        assert record.__dict__.get("request_id") == ""

    def test_injects_tenant_and_project_from_scope(self):
        from engramia.telemetry.logging import _ContextInjectingFormatter
        from engramia._context import reset_scope, set_scope
        from engramia.types import Scope

        fmt = _ContextInjectingFormatter("%(message)s")
        token = set_scope(Scope(tenant_id="acme", project_id="prod"))
        try:
            record = self._make_record()
            fmt.format(record)
            assert record.__dict__.get("tenant_id") == "acme"
            assert record.__dict__.get("project_id") == "prod"
        finally:
            reset_scope(token)

    def test_injects_empty_trace_when_otel_unavailable(self):
        from engramia.telemetry.logging import _ContextInjectingFormatter

        fmt = _ContextInjectingFormatter("%(message)s")
        with patch.dict(sys.modules, {"opentelemetry": None, "opentelemetry.trace": None}):
            record = self._make_record()
            fmt.format(record)
        assert record.__dict__.get("trace_id") == ""
        assert record.__dict__.get("span_id") == ""

    def test_format_does_not_raise_on_broken_context(self):
        from engramia.telemetry.logging import _ContextInjectingFormatter

        fmt = _ContextInjectingFormatter("%(message)s")
        record = self._make_record()

        with patch("engramia.telemetry.context.get_request_id", side_effect=RuntimeError("ctx broken")):
            # Should not propagate the exception
            result = fmt.format(record)
        assert "test message" in result


class TestConfigureJsonLogging:
    def test_no_op_when_python_json_logger_missing(self, caplog):
        """configure_json_logging() emits a warning and returns cleanly."""
        with patch.dict(sys.modules, {
            "pythonjsonlogger": None,
            "pythonjsonlogger.jsonlogger": None,
        }):
            import engramia.telemetry.logging as mod
            import importlib
            importlib.reload(mod)

            with caplog.at_level(logging.WARNING):
                mod.configure_json_logging()

            assert any("python-json-logger" in r.message for r in caplog.records)

    def test_installs_formatter_when_handler_present(self):
        """configure_json_logging() replaces the first handler's formatter."""
        import pytest
        pytest.importorskip("pythonjsonlogger", reason="pythonjsonlogger not installed")

        from engramia.telemetry.logging import configure_json_logging

        root = logging.getLogger()
        handler = logging.StreamHandler()
        original_handlers = root.handlers[:]
        root.handlers = [handler]
        try:
            configure_json_logging()
            assert handler.formatter is not None
        finally:
            root.handlers = original_handlers
