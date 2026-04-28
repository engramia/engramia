# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.providers.demo (DemoProvider + DemoMeter)."""

from __future__ import annotations

import json

import pytest

from engramia._context import reset_scope, set_scope
from engramia.exceptions import QuotaExceededError
from engramia.providers.demo import DemoMeter, DemoProvider
from engramia.types import Scope


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """DemoMeter is a process-wide singleton — clear between tests."""
    DemoMeter.instance().reset()


@pytest.fixture
def tenant_scope():
    """Set scope to a fresh tenant_id and clean up after the test."""
    token = set_scope(Scope(tenant_id="tenant-demo-1", project_id="proj-demo"))
    try:
        yield
    finally:
        reset_scope(token)


# ---------------------------------------------------------------------------
# DemoProvider response shape
# ---------------------------------------------------------------------------


class TestDemoProviderResponse:
    def test_default_role_returns_demo_message(self, tenant_scope) -> None:
        provider = DemoProvider()
        result = provider.call("any prompt")
        assert "DEMO" in result
        assert "LLM API key" in result

    def test_eval_role_returns_valid_json(self, tenant_scope) -> None:
        """MultiEvaluator parses the response with extract_json_from_llm —
        the demo response MUST be valid JSON with the expected keys."""
        provider = DemoProvider()
        result = provider.call("evaluate this", role="eval")
        parsed = json.loads(result)
        # MultiEvaluator's _parse_score expects these keys
        assert {"task_alignment", "code_quality", "workspace_usage", "robustness", "overall"} <= set(parsed)
        assert "DEMO" in parsed["feedback"]

    def test_eval_response_is_deterministic(self, tenant_scope) -> None:
        """Two consecutive demo eval calls return identical content. The
        MultiEvaluator's variance detector reads max-min over runs; identical
        values keep variance at 0."""
        provider = DemoProvider()
        a = provider.call("x", role="eval")
        b = provider.call("y", role="eval")
        assert a == b

    def test_eval_scores_are_neutral(self, tenant_scope) -> None:
        """Demo scores should be middle-of-the-road so the MultiEvaluator's
        variance and adversarial detectors stay quiet."""
        provider = DemoProvider()
        parsed = json.loads(provider.call("x", role="eval"))
        assert 4 <= parsed["overall"] <= 8
        for key in ("task_alignment", "code_quality", "workspace_usage", "robustness"):
            assert 4 <= parsed[key] <= 8


# ---------------------------------------------------------------------------
# DemoMeter quota
# ---------------------------------------------------------------------------


class TestDemoMeterQuota:
    def test_first_50_calls_allowed(self, tenant_scope) -> None:
        provider = DemoProvider()
        for _ in range(50):
            provider.call("x")  # must not raise

    def test_51st_call_raises_quota_exceeded(self, tenant_scope) -> None:
        provider = DemoProvider()
        for _ in range(50):
            provider.call("x")
        with pytest.raises(QuotaExceededError, match="Demo mode quota"):
            provider.call("x")

    def test_quota_is_per_tenant(self) -> None:
        """One tenant exhausting the quota does not affect another."""
        token1 = set_scope(Scope(tenant_id="tenant-A", project_id="p"))
        try:
            provider = DemoProvider()
            for _ in range(50):
                provider.call("x")
            with pytest.raises(QuotaExceededError):
                provider.call("x")
        finally:
            reset_scope(token1)

        # Different tenant — fresh budget
        token2 = set_scope(Scope(tenant_id="tenant-B", project_id="p"))
        try:
            provider = DemoProvider()
            provider.call("x")  # must not raise
        finally:
            reset_scope(token2)


# ---------------------------------------------------------------------------
# DemoMeter periodicity (calendar-month boundary)
# ---------------------------------------------------------------------------


class TestDemoMeterPeriodicity:
    def test_get_count_returns_current_period_only(self, tenant_scope) -> None:
        meter = DemoMeter.instance()
        assert meter.get_count("tenant-demo-1") == 0
        meter.try_increment("tenant-demo-1")
        assert meter.get_count("tenant-demo-1") == 1

    def test_reset_clears_counters(self, tenant_scope) -> None:
        meter = DemoMeter.instance()
        for _ in range(10):
            meter.try_increment("tenant-demo-1")
        assert meter.get_count("tenant-demo-1") == 10
        meter.reset()
        assert meter.get_count("tenant-demo-1") == 0


# ---------------------------------------------------------------------------
# DemoMeter thread safety (smoke)
# ---------------------------------------------------------------------------


class TestDemoMeterConcurrency:
    def test_concurrent_increments_do_not_overshoot(self) -> None:
        """Counter must not exceed the cap under concurrent access from
        many threads. Smoke test for the lock — not a stress test."""
        import threading

        token = set_scope(Scope(tenant_id="tenant-concurrent", project_id="p"))
        try:
            meter = DemoMeter.instance()
            successes: list[bool] = []
            lock = threading.Lock()

            def worker() -> None:
                ok = meter.try_increment("tenant-concurrent")
                with lock:
                    successes.append(ok)

            threads = [threading.Thread(target=worker) for _ in range(200)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            allowed = sum(1 for s in successes if s)
            denied = sum(1 for s in successes if not s)
            assert allowed == 50
            assert denied == 150
        finally:
            reset_scope(token)


# ---------------------------------------------------------------------------
# Custom meter injection (for tests / per-instance isolation)
# ---------------------------------------------------------------------------


class TestCustomMeter:
    def test_provider_uses_injected_meter(self, tenant_scope) -> None:
        custom = DemoMeter()
        provider = DemoProvider(meter=custom)
        provider.call("x")
        # Singleton must be untouched
        assert DemoMeter.instance().get_count("tenant-demo-1") == 0
        # But the injected meter has the count
        assert custom.get_count("tenant-demo-1") == 1
