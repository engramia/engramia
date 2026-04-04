# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for ROICollector and ROIAggregator (Phase 5.7)."""

import time
from unittest.mock import MagicMock, patch

import pytest

import engramia.analytics.collector as collector_module
from engramia._context import reset_scope, set_scope
from engramia.analytics.aggregator import ROIAggregator, _compute_rollup
from engramia.analytics.collector import ROICollector, _EVENTS_KEY
from engramia.analytics.models import EventKind, LearnSummary, ROIEvent, RecallOutcome
from engramia.providers.json_storage import JSONStorage
from engramia.types import Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path):
    return JSONStorage(path=tmp_path)


@pytest.fixture
def collector(storage):
    return ROICollector(storage)


@pytest.fixture
def aggregator(storage, collector):
    return ROIAggregator(storage, collector)


@pytest.fixture(autouse=True)
def reset_scope_after():
    """Reset contextvar scope after every test to avoid cross-test contamination."""
    token = set_scope(Scope())
    yield
    reset_scope(token)


# ---------------------------------------------------------------------------
# ROICollector — record_learn
# ---------------------------------------------------------------------------


class TestROICollectorRecordLearn:
    def test_appends_learn_event(self, collector):
        collector.record_learn(pattern_key="patterns/abc", eval_score=7.5)
        events = collector.load_events()
        assert len(events) == 1
        e = events[0]
        assert e.kind == EventKind.LEARN
        assert e.eval_score == 7.5
        assert e.pattern_key == "patterns/abc"

    def test_learn_event_captures_scope(self, storage):
        # Must load events while scope is still active — JSONStorage is scope-aware
        c = ROICollector(storage)
        token = set_scope(Scope(tenant_id="acme", project_id="proj1"))
        c.record_learn(pattern_key="patterns/x", eval_score=9.0)
        events = c.load_events()  # load before resetting scope
        reset_scope(token)
        assert len(events) == 1
        assert events[0].scope_tenant == "acme"
        assert events[0].scope_project == "proj1"

    def test_learn_event_has_timestamp(self, collector, monkeypatch):
        fixed_ts = 1_700_000_000.0
        monkeypatch.setattr(time, "time", lambda: fixed_ts)
        collector.record_learn(pattern_key="patterns/ts", eval_score=5.0)
        events = collector.load_events()
        assert events[0].ts == fixed_ts

    def test_multiple_learn_events(self, collector):
        for i in range(5):
            collector.record_learn(pattern_key=f"patterns/p{i}", eval_score=float(i))
        events = collector.load_events()
        assert len(events) == 5


# ---------------------------------------------------------------------------
# ROICollector — record_recall
# ---------------------------------------------------------------------------


class TestROICollectorRecordRecall:
    def test_appends_recall_event(self, collector):
        collector.record_recall(best_similarity=0.9, best_reuse_tier="duplicate", best_pattern_key="patterns/abc")
        events = collector.load_events()
        assert len(events) == 1
        e = events[0]
        assert e.kind == EventKind.RECALL
        assert e.similarity == pytest.approx(0.9)
        assert e.reuse_tier == "duplicate"
        assert e.pattern_key == "patterns/abc"

    def test_recall_with_no_match(self, collector):
        collector.record_recall(best_similarity=None, best_reuse_tier=None, best_pattern_key="")
        events = collector.load_events()
        assert len(events) == 1
        e = events[0]
        assert e.similarity is None
        assert e.reuse_tier is None
        assert e.pattern_key == ""

    def test_recall_event_captures_scope(self, storage):
        c = ROICollector(storage)
        token = set_scope(Scope(tenant_id="tenant_b", project_id="proj_b"))
        c.record_recall(best_similarity=0.7, best_reuse_tier="adapt", best_pattern_key="patterns/q")
        events = c.load_events()  # load before resetting scope
        reset_scope(token)
        assert len(events) == 1
        assert events[0].scope_tenant == "tenant_b"
        assert events[0].scope_project == "proj_b"


# ---------------------------------------------------------------------------
# ROICollector — fire-and-ignore
# ---------------------------------------------------------------------------


class TestROICollectorFireAndIgnore:
    def test_record_learn_does_not_raise_on_storage_failure(self, tmp_path):
        bad_storage = MagicMock()
        bad_storage.load.return_value = []
        bad_storage.save.side_effect = RuntimeError("disk full")
        c = ROICollector(bad_storage)
        # Must not raise — fire-and-ignore contract
        c.record_learn(pattern_key="patterns/x", eval_score=8.0)

    def test_record_recall_does_not_raise_on_storage_failure(self, tmp_path):
        bad_storage = MagicMock()
        bad_storage.load.return_value = []
        bad_storage.save.side_effect = OSError("io error")
        c = ROICollector(bad_storage)
        c.record_recall(best_similarity=0.8, best_reuse_tier="duplicate", best_pattern_key="k")

    def test_record_learn_logs_warning_on_failure(self, tmp_path, caplog):
        import logging

        bad_storage = MagicMock()
        bad_storage.load.side_effect = Exception("kaboom")
        c = ROICollector(bad_storage)
        with caplog.at_level(logging.WARNING, logger="engramia.analytics.collector"):
            c.record_learn(pattern_key="p", eval_score=5.0)
        assert any("ROICollector.record_learn failed silently" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# ROICollector — rolling window
# ---------------------------------------------------------------------------


class TestROICollectorRollingWindow:
    def test_rolling_window_drops_oldest_events(self, storage, monkeypatch):
        monkeypatch.setattr(collector_module, "_MAX_EVENTS", 3)
        c = ROICollector(storage)
        for i in range(4):
            c.record_learn(pattern_key=f"patterns/p{i}", eval_score=float(i))
        events = c.load_events()
        assert len(events) == 3
        # Oldest (eval_score=0.0) should be dropped
        scores = [e.eval_score for e in events]
        assert 0.0 not in scores
        assert 3.0 in scores


# ---------------------------------------------------------------------------
# ROICollector — filtering
# ---------------------------------------------------------------------------


class TestROICollectorFiltering:
    def test_scope_filtering_by_tenant(self, storage):
        # Inject events with different tenant tags directly into storage
        # (bypasses scope-aware storage routing, tests in-memory filter logic)
        c = ROICollector(storage)
        events_data = [
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=8.0,
                     scope_tenant="tenant_a", scope_project="p").model_dump(),
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=6.0,
                     scope_tenant="tenant_b", scope_project="p").model_dump(),
        ]
        storage.save(_EVENTS_KEY, events_data)

        events_a = c.load_events(tenant_id="tenant_a")
        assert len(events_a) == 1
        assert events_a[0].scope_tenant == "tenant_a"

        events_b = c.load_events(tenant_id="tenant_b")
        assert len(events_b) == 1
        assert events_b[0].scope_tenant == "tenant_b"

    def test_scope_filtering_by_project(self, storage):
        c = ROICollector(storage)
        events_data = [
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=7.0,
                     scope_tenant="t", scope_project="proj1").model_dump(),
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=5.0,
                     scope_tenant="t", scope_project="proj2").model_dump(),
        ]
        storage.save(_EVENTS_KEY, events_data)

        events = c.load_events(project_id="proj1")
        assert len(events) == 1
        assert events[0].scope_project == "proj1"

    def test_time_filtering_since_ts(self, storage):
        c = ROICollector(storage)
        # Manually inject an old event
        old_event = ROIEvent(
            kind=EventKind.LEARN,
            ts=1_000_000.0,  # very old
            eval_score=4.0,
            pattern_key="patterns/old",
        )
        storage.save(_EVENTS_KEY, [old_event.model_dump()])
        c.record_learn(pattern_key="patterns/new", eval_score=9.0)

        recent = c.load_events(since_ts=time.time() - 60)
        assert all(e.ts >= time.time() - 60 for e in recent)
        assert all(e.pattern_key != "patterns/old" for e in recent)

    def test_load_events_empty_returns_empty_list(self, collector):
        assert collector.load_events() == []

    def test_malformed_events_in_storage_are_skipped(self, storage):
        storage.save(_EVENTS_KEY, [{"bad": "data"}, {"kind": "learn", "ts": time.time()}])
        c = ROICollector(storage)
        # Should not raise; both records are missing required fields and must be silently dropped
        events = c.load_events()
        assert events == []


# ---------------------------------------------------------------------------
# _compute_rollup — pure function tests
# ---------------------------------------------------------------------------


class TestComputeRollup:
    """Tests for the pure _compute_rollup helper."""

    def _make_learn_event(self, eval_score: float, tenant: str = "t", project: str = "p") -> ROIEvent:
        return ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=eval_score,
                        scope_tenant=tenant, scope_project=project)

    def _make_recall_event(self, tier: str, sim: float, tenant: str = "t", project: str = "p") -> ROIEvent:
        return ROIEvent(kind=EventKind.RECALL, ts=time.time(), reuse_tier=tier,
                        similarity=sim, scope_tenant=tenant, scope_project=project)

    def test_empty_events_all_zeros(self):
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", [])
        assert rollup.roi_score == 0.0
        assert rollup.recall.total == 0
        assert rollup.learn.total == 0

    def test_roi_formula_correctness(self):
        # 3 recalls: 2 duplicate, 1 fresh → reuse_rate = 2/3
        # 2 learns: avg_eval = (8 + 10) / 2 = 9.0
        # roi = 0.6 * (2/3) * 10 + 0.4 * 9.0 = 4.0 + 3.6 = 7.6
        events = [
            self._make_recall_event("duplicate", 0.95),
            self._make_recall_event("duplicate", 0.88),
            self._make_recall_event("fresh", 0.30),
            self._make_learn_event(8.0),
            self._make_learn_event(10.0),
        ]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.recall.total == 3
        assert rollup.recall.duplicate_hits == 2
        assert rollup.recall.fresh_misses == 1
        assert rollup.recall.reuse_rate == pytest.approx(2 / 3, abs=0.001)
        assert rollup.learn.total == 2
        assert rollup.learn.avg_eval_score == pytest.approx(9.0, abs=0.001)
        assert rollup.roi_score == pytest.approx(7.6, abs=0.01)

    def test_roi_clamped_to_10(self):
        # 100% reuse_rate + perfect eval → roi = 0.6*1*10 + 0.4*10 = 10.0
        events = [
            self._make_recall_event("duplicate", 1.0),
            self._make_learn_event(10.0),
        ]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.roi_score <= 10.0

    def test_roi_clamped_to_zero(self):
        # All fresh misses + zero eval scores → roi = 0.0
        events = [
            self._make_recall_event("fresh", 0.1),
            self._make_learn_event(0.0),
        ]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.roi_score >= 0.0

    def test_adapt_tier_counts_as_reuse(self):
        events = [
            self._make_recall_event("adapt", 0.7),
            self._make_recall_event("fresh", 0.2),
        ]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.recall.adapt_hits == 1
        assert rollup.recall.reuse_rate == pytest.approx(0.5)

    def test_only_learn_events_recall_zeros(self):
        events = [self._make_learn_event(7.0), self._make_learn_event(8.0)]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.recall.total == 0
        assert rollup.recall.reuse_rate == 0.0
        assert rollup.learn.total == 2

    def test_only_recall_events_learn_zeros(self):
        events = [self._make_recall_event("duplicate", 0.9)]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.learn.total == 0
        assert rollup.learn.avg_eval_score == 0.0

    def test_p50_and_p90_eval_scores(self):
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        events = [self._make_learn_event(s) for s in scores]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        # median of 1..10 = 5.5
        assert rollup.learn.p50_eval_score == pytest.approx(5.5, abs=0.1)
        # p90 index = max(0, int(10 * 0.9) - 1) = 8 → scores[8] = 9.0
        assert rollup.learn.p90_eval_score == pytest.approx(9.0, abs=0.1)

    def test_avg_similarity_computed(self):
        events = [
            self._make_recall_event("duplicate", 0.9),
            self._make_recall_event("adapt", 0.7),
        ]
        rollup = _compute_rollup("t", "p", "daily", "2026-01-01T00:00:00Z", "2026-01-01T12:00:00Z", events)
        assert rollup.recall.avg_similarity == pytest.approx(0.8, abs=0.001)


# ---------------------------------------------------------------------------
# ROIAggregator — integration tests
# ---------------------------------------------------------------------------


class TestROIAggregator:
    def _seed_events(self, storage, tenant="default", project="default"):
        """Directly write events to storage for aggregator tests."""
        events = [
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=8.0,
                     scope_tenant=tenant, scope_project=project),
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=6.0,
                     scope_tenant=tenant, scope_project=project),
            ROIEvent(kind=EventKind.RECALL, ts=time.time(), reuse_tier="duplicate",
                     similarity=0.95, scope_tenant=tenant, scope_project=project),
            ROIEvent(kind=EventKind.RECALL, ts=time.time(), reuse_tier="fresh",
                     similarity=0.3, scope_tenant=tenant, scope_project=project),
        ]
        storage.save(_EVENTS_KEY, [e.model_dump() for e in events])

    def test_rollup_daily_produces_result(self, aggregator, storage):
        self._seed_events(storage)
        results = aggregator.rollup("daily")
        assert len(results) == 1
        r = results[0]
        assert r.window == "daily"
        assert r.learn.total == 2
        assert r.recall.total == 2

    def test_rollup_empty_events_returns_empty_list(self, aggregator):
        results = aggregator.rollup("daily")
        assert results == []

    def test_rollup_invalid_window_raises(self, aggregator):
        with pytest.raises(ValueError, match="Unsupported window"):
            aggregator.rollup("monthly")

    def test_get_rollup_returns_persisted_result(self, aggregator, storage):
        self._seed_events(storage)
        aggregator.rollup("daily")
        loaded = aggregator.get_rollup("daily", "default", "default")
        assert loaded is not None
        assert loaded.window == "daily"
        assert loaded.learn.total == 2

    def test_get_rollup_returns_none_when_missing(self, aggregator):
        result = aggregator.get_rollup("daily", "nonexistent", "nonexistent")
        assert result is None

    def test_rollup_multi_scope_produces_separate_rollups(self, storage, collector):
        agg = ROIAggregator(storage, collector)
        events = [
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=9.0,
                     scope_tenant="tenant_a", scope_project="proj"),
            ROIEvent(kind=EventKind.LEARN, ts=time.time(), eval_score=5.0,
                     scope_tenant="tenant_b", scope_project="proj"),
        ]
        storage.save(_EVENTS_KEY, [e.model_dump() for e in events])
        results = agg.rollup("daily")
        assert len(results) == 2
        tenants = {r.tenant_id for r in results}
        assert tenants == {"tenant_a", "tenant_b"}

    def test_rollup_idempotent_for_same_window(self, aggregator, storage):
        self._seed_events(storage)
        results1 = aggregator.rollup("daily")
        results2 = aggregator.rollup("daily")
        assert results1[0].roi_score == results2[0].roi_score

    def test_rollup_hourly_weekly_windows(self, aggregator, storage):
        self._seed_events(storage)
        for window in ("hourly", "weekly"):
            results = aggregator.rollup(window)
            assert len(results) == 1
            assert results[0].window == window

    def test_rollup_roi_score_in_valid_range(self, aggregator, storage):
        self._seed_events(storage)
        results = aggregator.rollup("daily")
        assert 0.0 <= results[0].roi_score <= 10.0
