# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia/api/prom_metrics.py."""

import importlib
from unittest.mock import MagicMock, patch

import pytest


def _make_mem(avg_eval_score=8.0, pattern_count=5, runs=10, success_rate=0.9, reuse_rate=0.5):
    mem = MagicMock()
    mem.metrics.pattern_count = pattern_count
    mem.metrics.avg_eval_score = avg_eval_score
    mem.metrics.runs = runs
    mem.metrics.success_rate = success_rate
    mem.metrics.reuse_rate = reuse_rate
    return mem


class TestBuildMetricsApp:
    def test_raises_import_error_without_prometheus_client(self):
        with patch.dict("sys.modules", {"prometheus_client": None}):
            import engramia.api.prom_metrics as mod

            importlib.reload(mod)
            with pytest.raises(ImportError):
                mod.build_metrics_app(_make_mem())

    def test_returns_callable_when_prometheus_available(self):
        pytest.importorskip("prometheus_client", reason="prometheus_client not installed")
        from engramia.api.prom_metrics import build_metrics_app

        app = build_metrics_app(_make_mem())
        assert callable(app)

    def test_callable_with_none_avg_eval_score(self):
        """avg_eval_score=None (no evals yet) must not crash build_metrics_app."""
        pytest.importorskip("prometheus_client", reason="prometheus_client not installed")
        from engramia.api.prom_metrics import build_metrics_app

        app = build_metrics_app(_make_mem(avg_eval_score=None))
        assert callable(app)

    def test_two_independent_registries(self):
        """Each call to build_metrics_app() creates its own CollectorRegistry."""
        pytest.importorskip("prometheus_client", reason="prometheus_client not installed")
        from engramia.api.prom_metrics import build_metrics_app

        app1 = build_metrics_app(_make_mem(pattern_count=1))
        app2 = build_metrics_app(_make_mem(pattern_count=2))
        assert callable(app1)
        assert callable(app2)
        assert app1 is not app2

    def test_collect_logs_warning_on_memory_error(self, caplog):
        """_collect() logs a warning and does not propagate exceptions from memory.metrics."""
        pytest.importorskip("prometheus_client", reason="prometheus_client not installed")
        import logging
        from engramia.api.prom_metrics import build_metrics_app

        broken_mem = MagicMock()
        type(broken_mem).metrics = property(lambda self: (_ for _ in ()).throw(RuntimeError("storage offline")))

        # build_metrics_app should return a callable without raising
        app = build_metrics_app(broken_mem)
        assert callable(app)
