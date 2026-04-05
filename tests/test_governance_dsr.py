# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for DSRTracker (engramia/governance/dsr.py).

Uses the in-memory fallback (engine=None) so no database is needed.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

from engramia.governance.dsr import DSRRequest, DSRTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracker() -> DSRTracker:
    """Fresh DSRTracker with isolated in-memory store per test."""
    import engramia.governance.dsr as dsr_module
    dsr_module._mem_store.clear()
    return DSRTracker(engine=None)


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


class TestCreate:
    def test_returns_dsr_request(self):
        tracker = _tracker()
        req = tracker.create("t1", "erasure", "user@example.com")
        assert isinstance(req, DSRRequest)
        assert req.tenant_id == "t1"
        assert req.request_type == "erasure"
        assert req.subject_email == "user@example.com"
        assert req.status == "pending"

    def test_id_is_uuid(self):
        import uuid
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        uuid.UUID(req.id)  # raises if not valid UUID

    def test_deadline_is_sla_days_in_future(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        created = datetime.datetime.fromisoformat(req.created_at)
        deadline = datetime.datetime.fromisoformat(req.deadline)
        delta = deadline - created
        assert 29 <= delta.days <= 31  # SLA_DAYS ± rounding

    def test_persists_to_memory_store(self):
        tracker = _tracker()
        req = tracker.create("t1", "portability", "x@y.com")
        assert tracker.get(req.id) is not None

    def test_notes_stored(self):
        tracker = _tracker()
        req = tracker.create("t1", "erasure", "a@b.com", notes="Received by email")
        assert req.notes == "Received by email"

    def test_all_request_types_accepted(self):
        tracker = _tracker()
        for rtype in ("access", "erasure", "portability", "rectification"):
            req = tracker.create("t1", rtype, "a@b.com")
            assert req.request_type == rtype


# ---------------------------------------------------------------------------
# update_status()
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_status_updated(self):
        tracker = _tracker()
        req = tracker.create("t1", "erasure", "a@b.com")
        updated = tracker.update_status(req.id, "in_progress")
        assert updated.status == "in_progress"

    def test_completed_at_set_on_completion(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        updated = tracker.update_status(req.id, "completed")
        assert updated.completed_at is not None

    def test_completed_at_set_on_rejection(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        updated = tracker.update_status(req.id, "rejected")
        assert updated.completed_at is not None

    def test_notes_appended(self):
        tracker = _tracker()
        req = tracker.create("t1", "erasure", "a@b.com", notes="Initial note")
        updated = tracker.update_status(req.id, "in_progress", notes="Operator review started")
        assert "Initial note" in updated.notes
        assert "Operator review started" in updated.notes

    def test_returns_none_for_unknown_id(self):
        tracker = _tracker()
        result = tracker.update_status("nonexistent-id", "completed")
        assert result is None

    def test_updated_at_changes(self):
        tracker = _tracker()
        req = tracker.create("t1", "portability", "a@b.com")
        original_updated = req.updated_at
        updated = tracker.update_status(req.id, "in_progress")
        # updated_at may equal created_at in fast test runs — just ensure it's a valid ISO datetime
        datetime.datetime.fromisoformat(updated.updated_at)
        assert updated.updated_at >= original_updated


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestGet:
    def test_returns_dsr_by_id(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        fetched = tracker.get(req.id)
        assert fetched is not None
        assert fetched.id == req.id

    def test_returns_none_for_missing_id(self):
        tracker = _tracker()
        assert tracker.get("does-not-exist") is None


# ---------------------------------------------------------------------------
# list_requests()
# ---------------------------------------------------------------------------


class TestListRequests:
    def test_returns_only_tenant_requests(self):
        tracker = _tracker()
        tracker.create("t1", "access", "a@b.com")
        tracker.create("t2", "erasure", "c@d.com")
        result = tracker.list_requests("t1")
        assert all(r.tenant_id == "t1" for r in result)
        assert len(result) == 1

    def test_filter_by_status(self):
        tracker = _tracker()
        req = tracker.create("t1", "erasure", "a@b.com")
        tracker.create("t1", "access", "b@b.com")
        tracker.update_status(req.id, "completed")
        pending = tracker.list_requests("t1", status="pending")
        assert all(r.status == "pending" for r in pending)
        assert len(pending) == 1

    def test_returns_empty_for_unknown_tenant(self):
        tracker = _tracker()
        assert tracker.list_requests("unknown-tenant") == []

    def test_sorted_by_created_at_descending(self):
        tracker = _tracker()
        r1 = tracker.create("t1", "access", "a@b.com")
        r2 = tracker.create("t1", "erasure", "b@b.com")
        result = tracker.list_requests("t1")
        # More recently created should come first
        assert result[0].created_at >= result[1].created_at


# ---------------------------------------------------------------------------
# overdue property
# ---------------------------------------------------------------------------


class TestOverdue:
    def test_not_overdue_when_pending_within_sla(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        assert req.overdue is False

    def test_overdue_when_deadline_passed(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        # Manually set deadline in the past
        past = (datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=1)).isoformat()
        req.deadline = past
        assert req.overdue is True

    def test_completed_request_never_overdue(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        req.status = "completed"
        past = (datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=1)).isoformat()
        req.deadline = past
        assert req.overdue is False

    def test_rejected_request_never_overdue(self):
        tracker = _tracker()
        req = tracker.create("t1", "erasure", "a@b.com")
        req.status = "rejected"
        past = (datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=1)).isoformat()
        req.deadline = past
        assert req.overdue is False

    def test_overdue_only_filter(self):
        tracker = _tracker()
        req1 = tracker.create("t1", "access", "a@b.com")
        req2 = tracker.create("t1", "erasure", "b@b.com")
        # Make req1 overdue
        import engramia.governance.dsr as dsr_module
        dsr_module._mem_store[req1.id].deadline = (
            datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=1)
        ).isoformat()

        result = tracker.list_requests("t1", overdue_only=True)
        assert len(result) == 1
        assert result[0].id == req1.id


# ---------------------------------------------------------------------------
# pending_count()
# ---------------------------------------------------------------------------


class TestPendingCount:
    def test_counts_by_status(self):
        tracker = _tracker()
        req1 = tracker.create("t1", "access", "a@b.com")
        req2 = tracker.create("t1", "erasure", "b@b.com")
        tracker.update_status(req2.id, "in_progress")
        counts = tracker.pending_count("t1")
        assert counts["pending"] == 1
        assert counts["in_progress"] == 1
        assert counts["overdue"] == 0

    def test_completed_not_counted(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        tracker.update_status(req.id, "completed")
        counts = tracker.pending_count("t1")
        assert counts["pending"] == 0
        assert counts["in_progress"] == 0

    def test_overdue_counted(self):
        tracker = _tracker()
        req = tracker.create("t1", "access", "a@b.com")
        import engramia.governance.dsr as dsr_module
        dsr_module._mem_store[req.id].deadline = (
            datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=1)
        ).isoformat()
        counts = tracker.pending_count("t1")
        assert counts["overdue"] == 1
