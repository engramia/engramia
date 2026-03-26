"""Tests for MetricsStore."""

import pytest

from agent_brain.core.metrics import MetricsStore


@pytest.fixture
def metrics(storage):
    return MetricsStore(storage)


def test_initial_metrics_are_zero(metrics):
    m = metrics.get()
    assert m.runs == 0
    assert m.success == 0
    assert m.failures == 0
    assert m.pipeline_reuse == 0
    assert m.success_rate == 0.0


def test_record_success(metrics):
    metrics.record_run(success=True)
    m = metrics.get()
    assert m.runs == 1
    assert m.success == 1
    assert m.failures == 0
    assert m.success_rate == 1.0


def test_record_failure(metrics):
    metrics.record_run(success=False)
    m = metrics.get()
    assert m.runs == 1
    assert m.failures == 1
    assert m.success_rate == 0.0


def test_success_rate_calculation(metrics):
    metrics.record_run(success=True)
    metrics.record_run(success=True)
    metrics.record_run(success=False)
    m = metrics.get()
    assert m.runs == 3
    assert m.success_rate == pytest.approx(0.667, abs=0.001)


def test_pipeline_reuse_tracking(metrics):
    metrics.record_run(success=True, pipeline_reuse=True)
    m = metrics.get()
    assert m.pipeline_reuse == 1


def test_metrics_persist_across_instances(storage):
    m1 = MetricsStore(storage)
    m1.record_run(success=True)
    m1.record_run(success=False)

    m2 = MetricsStore(storage)
    m = m2.get()
    assert m.runs == 2
    assert m.success == 1
