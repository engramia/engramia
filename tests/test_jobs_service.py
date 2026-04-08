# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for engramia/jobs/service.py.

Tests the in-memory path without any external services, and the DB path
using a mocked SQLAlchemy engine.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from engramia._context import reset_scope, set_scope
from engramia.jobs.models import JobOperation, JobStatus
from engramia.jobs.service import JobService
from engramia.types import Scope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def default_scope():
    token = set_scope(Scope(tenant_id="test", project_id="default"))
    yield
    reset_scope(token)


@pytest.fixture
def svc():
    """In-memory JobService (no engine, no memory needed for submit/get/list)."""
    return JobService(engine=None, memory=None)


@pytest.fixture
def mem_mock():
    return MagicMock()


# ---------------------------------------------------------------------------
# In-memory — submit / get / list
# ---------------------------------------------------------------------------


class TestJobServiceMemorySubmit:
    def test_submit_returns_pending_job(self, svc):
        result = svc.submit("aging", {})
        assert result.status == JobStatus.PENDING
        assert result.job_id

    def test_submit_unknown_operation_raises(self, svc):
        with pytest.raises(ValueError, match="Unknown operation"):
            svc.submit("nonexistent_op", {})

    def test_get_returns_job_info(self, svc):
        result = svc.submit("aging", {})
        info = svc.get(result.job_id)
        assert info.id == result.job_id
        assert info.status == JobStatus.PENDING

    def test_get_returns_none_for_unknown_id(self, svc):
        assert svc.get("no-such-id") is None

    def test_get_respects_scope_isolation(self, svc):
        result = svc.submit("aging", {})
        token = set_scope(Scope(tenant_id="other_tenant", project_id="default"))
        try:
            assert svc.get(result.job_id) is None
        finally:
            reset_scope(token)

    def test_list_returns_submitted_jobs(self, svc):
        svc.submit("aging", {})
        svc.submit("aging", {})
        jobs = svc.list_jobs()
        assert len(jobs) == 2

    def test_list_filters_by_status(self, svc):
        svc.submit("aging", {})
        jobs_pending = svc.list_jobs(status="pending")
        jobs_completed = svc.list_jobs(status="completed")
        assert len(jobs_pending) == 1
        assert len(jobs_completed) == 0

    def test_list_respects_scope_isolation(self, svc):
        svc.submit("aging", {})
        token = set_scope(Scope(tenant_id="other", project_id="default"))
        try:
            assert svc.list_jobs() == []
        finally:
            reset_scope(token)

    def test_list_limit_respected(self, svc):
        for _ in range(5):
            svc.submit("aging", {})
        assert len(svc.list_jobs(limit=2)) == 2


# ---------------------------------------------------------------------------
# In-memory — cancel
# ---------------------------------------------------------------------------


class TestJobServiceMemoryCancel:
    def test_cancel_pending_job_returns_true(self, svc):
        result = svc.submit("aging", {})
        assert svc.cancel(result.job_id) is True
        info = svc.get(result.job_id)
        assert info.status == JobStatus.CANCELLED

    def test_cancel_unknown_job_returns_false(self, svc):
        assert svc.cancel("no-such-id") is False

    def test_cancel_out_of_scope_returns_false(self, svc):
        result = svc.submit("aging", {})
        token = set_scope(Scope(tenant_id="other", project_id="default"))
        try:
            assert svc.cancel(result.job_id) is False
        finally:
            reset_scope(token)

    def test_cancel_running_job_returns_false(self, svc, mem_mock):
        svc._memory = mem_mock
        mem_mock.run_aging.return_value = 0
        result = svc.submit("aging", {})
        # Manually set to running
        svc._mem_store[result.job_id]["status"] = JobStatus.RUNNING
        assert svc.cancel(result.job_id) is False


# ---------------------------------------------------------------------------
# In-memory — poll_and_execute (success path)
# ---------------------------------------------------------------------------


class TestJobServiceMemoryPoll:
    def test_poll_executes_pending_job(self, svc, mem_mock):
        svc._memory = mem_mock
        mem_mock.run_aging.return_value = 3

        result = svc.submit("aging", {})
        count = svc.poll_and_execute(batch_size=1)
        assert count == 1
        info = svc.get(result.job_id)
        assert info.status == JobStatus.COMPLETED
        assert info.result == {"pruned": 3}

    def test_poll_does_nothing_when_no_pending(self, svc):
        count = svc.poll_and_execute()
        assert count == 0

    def test_poll_respects_batch_size(self, svc, mem_mock):
        svc._memory = mem_mock
        mem_mock.run_aging.return_value = 0
        for _ in range(3):
            svc.submit("aging", {})
        count = svc.poll_and_execute(batch_size=2)
        assert count == 2

    def test_poll_skips_scheduled_future_job(self, svc, mem_mock):
        svc._memory = mem_mock
        result = svc.submit("aging", {})
        future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        svc._mem_store[result.job_id]["scheduled_at"] = future
        count = svc.poll_and_execute()
        assert count == 0


# ---------------------------------------------------------------------------
# In-memory — execute_job failure paths
# ---------------------------------------------------------------------------


class TestJobServiceMemoryExecuteFailure:
    def test_failed_job_retries_with_backoff(self, svc, mem_mock):
        svc._memory = mem_mock
        mem_mock.run_aging.side_effect = RuntimeError("transient error")
        result = svc.submit("aging", {})

        svc.poll_and_execute()  # attempt 1 → fails, goes back to PENDING with scheduled_at
        info = svc.get(result.job_id)
        assert info.status == JobStatus.PENDING
        assert info.attempts == 1

    def test_job_marked_failed_after_max_attempts(self, svc, mem_mock):
        svc._memory = mem_mock
        mem_mock.run_aging.side_effect = RuntimeError("permanent error")
        result = svc.submit("aging", {})

        # Set attempts to max_attempts - 1 so next poll finishes it
        svc._mem_store[result.job_id]["attempts"] = 2

        svc.poll_and_execute()
        info = svc.get(result.job_id)
        assert info.status == JobStatus.FAILED
        assert "RuntimeError" in info.error

    def test_failed_job_not_picked_up_beyond_max_attempts(self, svc, mem_mock):
        svc._memory = mem_mock
        result = svc.submit("aging", {})
        svc._mem_store[result.job_id]["attempts"] = 3  # at max_attempts
        count = svc.poll_and_execute()
        assert count == 0  # should not be picked up


# ---------------------------------------------------------------------------
# In-memory — reap_expired
# ---------------------------------------------------------------------------


class TestJobServiceReapExpired:
    def test_reap_expired_marks_old_running_jobs(self, svc):
        result = svc.submit("aging", {})
        job = svc._mem_store[result.job_id]
        job["status"] = JobStatus.RUNNING
        past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
        job["expires_at"] = past

        reaped = svc.reap_expired()
        assert reaped == 1
        info = svc.get(result.job_id)
        assert info.status == JobStatus.EXPIRED

    def test_reap_expired_ignores_pending_jobs(self, svc):
        svc.submit("aging", {})
        reaped = svc.reap_expired()
        assert reaped == 0

    def test_reap_expired_ignores_future_expiry(self, svc):
        result = svc.submit("aging", {})
        job = svc._mem_store[result.job_id]
        job["status"] = JobStatus.RUNNING
        future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        job["expires_at"] = future
        assert svc.reap_expired() == 0


# ---------------------------------------------------------------------------
# DB path — mocked engine
# ---------------------------------------------------------------------------


def _make_db_svc(engine=None, mem=None):
    svc = JobService(engine=engine or MagicMock(), memory=mem)
    return svc


class TestJobServiceDBSubmit:
    def test_db_submit_calls_insert(self):
        engine = MagicMock()
        begin_inner = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(return_value=begin_inner)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        result = svc.submit("aging", {})
        assert result.status == JobStatus.PENDING
        begin_inner.execute.assert_called_once()

    def test_db_submit_unknown_operation_raises(self):
        svc = JobService(engine=MagicMock(), memory=None)
        with pytest.raises(ValueError, match="Unknown operation"):
            svc.submit("bad_op", {})


class TestJobServiceDBGet:
    def test_db_get_returns_none_when_not_found(self):
        engine = MagicMock()
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        assert svc.get("no-id") is None

    def test_db_get_returns_job_info_when_found(self):
        engine = MagicMock()
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (
            "job-1", "aging", "completed", {"pruned": 0}, None,
            1, "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z",
            "2026-01-01T00:00:02Z", None,
        )
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        info = svc.get("job-1")
        assert info.id == "job-1"
        assert info.status == "completed"


class TestJobServiceDBCancel:
    def test_db_cancel_returns_true_when_row_updated(self):
        engine = MagicMock()
        result = MagicMock()
        result.rowcount = 1
        conn = MagicMock()
        conn.execute.return_value = result
        engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        assert svc.cancel("some-job") is True

    def test_db_cancel_returns_false_when_no_row_updated(self):
        engine = MagicMock()
        result = MagicMock()
        result.rowcount = 0
        conn = MagicMock()
        conn.execute.return_value = result
        engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        assert svc.cancel("some-job") is False


class TestJobServiceDBReapExpired:
    def test_db_reap_expired_returns_count(self):
        engine = MagicMock()
        result = MagicMock()
        result.rowcount = 2
        conn = MagicMock()
        conn.execute.return_value = result
        engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        assert svc.reap_expired() == 2


# ---------------------------------------------------------------------------
# In-memory — max_execution_seconds
# ---------------------------------------------------------------------------


class TestJobServiceMaxExecutionSeconds:
    def test_submit_stores_max_execution_seconds(self, svc):
        result = svc.submit("aging", {}, max_execution_seconds=30)
        job = svc._mem_store[result.job_id]
        assert job["max_execution_seconds"] == 30

    def test_submit_without_max_execution_seconds_defaults_to_none(self, svc):
        result = svc.submit("aging", {})
        job = svc._mem_store[result.job_id]
        assert job["max_execution_seconds"] is None

    def test_job_expires_when_timeout_exceeded(self, svc, mem_mock):
        """A job whose dispatch takes longer than max_execution_seconds is marked expired."""
        import time as _time

        svc._memory = mem_mock

        def slow_aging():
            _time.sleep(5)
            return 0

        mem_mock.run_aging.side_effect = slow_aging

        result = svc.submit("aging", {}, max_execution_seconds=1)
        svc.poll_and_execute()

        info = svc.get(result.job_id)
        assert info.status == "expired"
        assert "max execution time" in (info.error or "")

    def test_job_completes_within_timeout(self, svc, mem_mock):
        """A job that finishes before the deadline is marked completed normally."""
        svc._memory = mem_mock
        mem_mock.run_aging.return_value = 2

        result = svc.submit("aging", {}, max_execution_seconds=60)
        svc.poll_and_execute()

        info = svc.get(result.job_id)
        assert info.status == "completed"

    def test_db_submit_passes_max_execution_seconds(self):
        engine = MagicMock()
        begin_inner = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(return_value=begin_inner)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        svc = JobService(engine=engine, memory=None)
        svc.submit("aging", {}, max_execution_seconds=120)

        call_kwargs = begin_inner.execute.call_args
        # The bound params dict is the second positional arg
        params = call_kwargs[0][1]
        assert params["max_exec"] == 120
