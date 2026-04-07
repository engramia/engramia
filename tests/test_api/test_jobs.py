# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Tests for the Phase 5.4 async job system.

Tests cover:
- JobService in-memory: submit, get, list, cancel, poll_and_execute, reap
- JobWorker: start/stop lifecycle
- API endpoints: GET /v1/jobs, GET /v1/jobs/{id}, POST /v1/jobs/{id}/cancel
- Dual-mode: Prefer: respond-async on evaluate/compose/aging/evolve/import
- Dispatch: operation -> Memory method mapping
- Retry + backoff on failure
- Scope isolation between tenants
"""

import json
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import engramia._factory as factory
from engramia import Memory
from engramia.jobs import JobService, JobStatus, JobWorker

pytestmark = pytest.mark.integration
from engramia.jobs.dispatch import dispatch_job
from engramia.jobs.models import JobOperation
from engramia.types import Scope

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EVAL_RESPONSE = json.dumps(
    {
        "task_alignment": 8,
        "code_quality": 7,
        "workspace_usage": 8,
        "robustness": 6,
        "overall": 7.5,
        "feedback": "Good job.",
    }
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.call.return_value = EVAL_RESPONSE
    return llm


@pytest.fixture
def memory(fake_embeddings, storage, mock_llm):
    return Memory(embeddings=fake_embeddings, storage=storage, llm=mock_llm)


@pytest.fixture
def job_service(memory):
    """In-memory JobService for testing (no Postgres)."""
    return JobService(engine=None, memory=memory)


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """TestClient with job service wired up via create_app()."""
    monkeypatch.setenv("ENGRAMIA_ALLOW_NO_AUTH", "true")
    monkeypatch.setenv("ENGRAMIA_AUTH_MODE", "dev")
    monkeypatch.setenv("ENGRAMIA_STORAGE", "json")
    monkeypatch.setenv("ENGRAMIA_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("ENGRAMIA_LLM_PROVIDER", "none")
    monkeypatch.setenv("ENGRAMIA_SKIP_AUTO_APP", "1")

    mock_embeddings = MagicMock()
    mock_embeddings.embed.return_value = [0.1] * 1536
    _mock_llm = MagicMock()
    _mock_llm.call.return_value = EVAL_RESPONSE

    monkeypatch.setattr(factory, "make_embeddings", lambda: mock_embeddings)
    monkeypatch.setattr(factory, "make_llm", lambda: _mock_llm)

    from engramia.api.app import create_app

    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# JobService — submit, get, list, cancel
# ---------------------------------------------------------------------------


class TestJobServiceSubmit:
    def test_submit_returns_pending(self, job_service):
        result = job_service.submit("evaluate", {"task": "t", "code": "c"})
        assert result.status == JobStatus.PENDING
        assert result.job_id

    def test_submit_unknown_operation_raises(self, job_service):
        with pytest.raises(ValueError, match="Unknown operation"):
            job_service.submit("nonexistent", {})

    def test_submit_all_operations(self, job_service):
        for op in JobOperation:
            result = job_service.submit(op.value, {"task": "t", "code": "c", "role": "r", "current_prompt": "p", "records": []})
            assert result.status == JobStatus.PENDING


class TestJobServiceGet:
    def test_get_returns_submitted_job(self, job_service):
        result = job_service.submit("evaluate", {"task": "t", "code": "c"})
        job = job_service.get(result.job_id)
        assert job.id == result.job_id
        assert job.operation == "evaluate"
        assert job.status == JobStatus.PENDING

    def test_get_nonexistent_returns_none(self, job_service):
        assert job_service.get("nonexistent-id") is None

    def test_get_enforces_scope(self, job_service):
        scope_a = Scope(tenant_id="a", project_id="p")
        scope_b = Scope(tenant_id="b", project_id="p")
        result = job_service.submit("aging", {}, scope=scope_a)
        job_a = job_service.get(result.job_id, scope=scope_a)
        assert job_a.id == result.job_id
        assert job_service.get(result.job_id, scope=scope_b) is None


class TestJobServiceList:
    def test_list_returns_jobs(self, job_service):
        job_service.submit("evaluate", {"task": "t", "code": "c"})
        job_service.submit("aging", {})
        jobs = job_service.list_jobs()
        assert len(jobs) == 2

    def test_list_filtered_by_status(self, job_service):
        job_service.submit("evaluate", {"task": "t", "code": "c"})
        jobs = job_service.list_jobs(status="completed")
        assert len(jobs) == 0
        jobs = job_service.list_jobs(status="pending")
        assert len(jobs) == 1

    def test_list_respects_limit(self, job_service):
        for _ in range(5):
            job_service.submit("aging", {})
        jobs = job_service.list_jobs(limit=3)
        assert len(jobs) == 3

    def test_list_enforces_scope(self, job_service):
        scope_a = Scope(tenant_id="a", project_id="p")
        scope_b = Scope(tenant_id="b", project_id="p")
        job_service.submit("aging", {}, scope=scope_a)
        job_service.submit("aging", {}, scope=scope_b)
        assert len(job_service.list_jobs(scope=scope_a)) == 1
        assert len(job_service.list_jobs(scope=scope_b)) == 1


class TestJobServiceCancel:
    def test_cancel_pending_job(self, job_service):
        result = job_service.submit("aging", {})
        assert job_service.cancel(result.job_id) is True
        job = job_service.get(result.job_id)
        assert job.status == JobStatus.CANCELLED

    def test_cancel_nonexistent_returns_false(self, job_service):
        assert job_service.cancel("nonexistent") is False

    def test_cancel_enforces_scope(self, job_service):
        scope_a = Scope(tenant_id="a", project_id="p")
        scope_b = Scope(tenant_id="b", project_id="p")
        result = job_service.submit("aging", {}, scope=scope_a)
        assert job_service.cancel(result.job_id, scope=scope_b) is False
        assert job_service.cancel(result.job_id, scope=scope_a) is True


# ---------------------------------------------------------------------------
# JobService — poll_and_execute
# ---------------------------------------------------------------------------


class TestJobServicePollAndExecute:
    def test_execute_aging_job(self, job_service):
        result = job_service.submit("aging", {})
        executed = job_service.poll_and_execute(batch_size=1)
        assert executed == 1
        job = job_service.get(result.job_id)
        assert job.status == JobStatus.COMPLETED
        assert "pruned" in job.result

    def test_execute_evaluate_job(self, job_service):
        result = job_service.submit("evaluate", {"task": "Test task", "code": "print('hello')"})
        executed = job_service.poll_and_execute()
        assert executed == 1
        job = job_service.get(result.job_id)
        assert job.status == JobStatus.COMPLETED
        assert "median_score" in job.result

    def test_execute_feedback_decay_job(self, job_service):
        result = job_service.submit("feedback_decay", {})
        job_service.poll_and_execute()
        job = job_service.get(result.job_id)
        assert job.status == JobStatus.COMPLETED

    def test_failed_job_retries(self, job_service):
        result = job_service.submit("evaluate", {"task": "t", "code": "c"})
        # Make the LLM fail
        job_service._memory._llm.call.side_effect = RuntimeError("LLM down")
        job_service.poll_and_execute()
        job = job_service.get(result.job_id)
        # Should be back to pending for retry
        assert job.status == JobStatus.PENDING
        assert job.attempts == 1

    def test_failed_job_exhausts_retries(self, job_service):
        result = job_service.submit("evaluate", {"task": "t", "code": "c"})
        job_service._memory._llm.call.side_effect = RuntimeError("LLM down")
        # Exhaust all 3 attempts — clear scheduled_at between polls to bypass backoff
        for _ in range(3):
            job = job_service._mem_store[result.job_id]
            job["scheduled_at"] = None  # bypass backoff delay for test
            job_service.poll_and_execute()
        job = job_service.get(result.job_id)
        assert job.status == JobStatus.FAILED
        assert isinstance(job.error, str) and len(job.error) > 0

    def test_poll_empty_queue(self, job_service):
        assert job_service.poll_and_execute() == 0

    def test_cancelled_job_not_executed(self, job_service):
        result = job_service.submit("aging", {})
        job_service.cancel(result.job_id)
        executed = job_service.poll_and_execute()
        assert executed == 0


# ---------------------------------------------------------------------------
# JobService — reap_expired
# ---------------------------------------------------------------------------


class TestJobServiceReap:
    def test_reap_expired_jobs(self, job_service):
        result = job_service.submit("aging", {})
        # Manually set job to running with expired timestamp
        job = job_service._mem_store[result.job_id]
        job["status"] = JobStatus.RUNNING
        job["expires_at"] = "2020-01-01T00:00:00Z"
        reaped = job_service.reap_expired()
        assert reaped == 1
        updated = job_service.get(result.job_id)
        assert updated.status == JobStatus.EXPIRED

    def test_reap_no_expired(self, job_service):
        job_service.submit("aging", {})
        assert job_service.reap_expired() == 0


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_unknown_raises(self, memory):
        with pytest.raises(ValueError, match="Unknown job operation"):
            dispatch_job(memory, "nonexistent", {})

    def test_dispatch_aging(self, memory):
        result = dispatch_job(memory, "aging", {})
        assert "pruned" in result

    def test_dispatch_feedback_decay(self, memory):
        result = dispatch_job(memory, "feedback_decay", {})
        assert "pruned" in result

    def test_dispatch_export(self, memory):
        result = dispatch_job(memory, "export", {})
        assert "records" in result
        assert "count" in result

    def test_dispatch_evaluate(self, memory):
        result = dispatch_job(memory, "evaluate", {"task": "Test", "code": "x=1"})
        assert "median_score" in result
        assert "scores" in result

    def test_dispatch_compose(self, memory):
        result = dispatch_job(memory, "compose", {"task": "Read and process"})
        assert "task" in result
        assert "stages" in result

    def test_dispatch_evolve(self, memory):
        result = dispatch_job(memory, "evolve", {"role": "coder", "current_prompt": "You are helpful."})
        assert "improved_prompt" in result

    def test_dispatch_import(self, memory):
        result = dispatch_job(memory, "import", {"records": [], "overwrite": False})
        assert result["imported"] == 0
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# JobWorker
# ---------------------------------------------------------------------------


class TestJobWorker:
    def test_start_stop(self, job_service):
        worker = JobWorker(service=job_service, poll_interval=0.1)
        worker.start()
        assert worker.running is True
        worker.stop(timeout=2.0)
        assert worker.running is False

    def test_worker_processes_job(self, job_service):
        import threading

        worker = JobWorker(service=job_service, poll_interval=0.1)
        job_service.submit("aging", {})
        worker.start()
        # Poll until the job completes rather than sleeping a fixed duration
        _poll = threading.Event()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if job_service.list_jobs()[0].status == JobStatus.COMPLETED:
                break
            _poll.wait(timeout=0.05)
        worker.stop(timeout=2.0)
        jobs = job_service.list_jobs()
        assert jobs[0].status == JobStatus.COMPLETED

    def test_double_start_ignored(self, job_service):
        worker = JobWorker(service=job_service, poll_interval=0.1)
        worker.start()
        worker.start()  # Should log warning but not crash
        worker.stop(timeout=2.0)


# ---------------------------------------------------------------------------
# API — Dual-mode (Prefer: respond-async)
# ---------------------------------------------------------------------------


class TestAsyncDualMode:
    def test_evaluate_sync_default(self, api_client):
        resp = api_client.post("/v1/evaluate", json={"task": "Test", "code": "print(1)"})
        assert resp.status_code == 200
        assert "median_score" in resp.json()

    def test_evaluate_async_with_header(self, api_client):
        resp = api_client.post(
            "/v1/evaluate",
            json={"task": "Test", "code": "print(1)"},
            headers={"Prefer": "respond-async"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert "Location" in resp.headers

    def test_compose_async(self, api_client):
        resp = api_client.post(
            "/v1/compose",
            json={"task": "Read CSV and compute stats"},
            headers={"Prefer": "respond-async"},
        )
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    def test_aging_async(self, api_client):
        resp = api_client.post("/v1/aging", headers={"Prefer": "respond-async"})
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    def test_feedback_decay_async(self, api_client):
        resp = api_client.post("/v1/feedback/decay", headers={"Prefer": "respond-async"})
        assert resp.status_code == 202

    def test_evolve_async(self, api_client):
        resp = api_client.post(
            "/v1/evolve",
            json={"role": "coder", "current_prompt": "You are a coder."},
            headers={"Prefer": "respond-async"},
        )
        assert resp.status_code == 202

    def test_import_async(self, api_client):
        resp = api_client.post(
            "/v1/import",
            json={"records": [], "overwrite": False},
            headers={"Prefer": "respond-async"},
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# API — Job endpoints
# ---------------------------------------------------------------------------


class TestJobEndpoints:
    def test_get_job(self, api_client):
        # Submit async job first
        resp = api_client.post("/v1/aging", headers={"Prefer": "respond-async"})
        job_id = resp.json()["job_id"]
        # Get it
        resp = api_client.get(f"/v1/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == job_id
        assert resp.json()["status"] == "pending"

    def test_get_job_not_found(self, api_client):
        resp = api_client.get("/v1/jobs/nonexistent-uuid")
        assert resp.status_code == 404

    def test_list_jobs(self, api_client):
        api_client.post("/v1/aging", headers={"Prefer": "respond-async"})
        api_client.post("/v1/aging", headers={"Prefer": "respond-async"})
        resp = api_client.get("/v1/jobs")
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 2

    def test_list_jobs_filter_status(self, api_client):
        api_client.post("/v1/aging", headers={"Prefer": "respond-async"})
        resp = api_client.get("/v1/jobs?status=completed")
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 0

    def test_cancel_job(self, api_client):
        resp = api_client.post("/v1/aging", headers={"Prefer": "respond-async"})
        job_id = resp.json()["job_id"]
        resp = api_client.post(f"/v1/jobs/{job_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True

    def test_cancel_nonexistent(self, api_client):
        resp = api_client.post("/v1/jobs/nonexistent/cancel")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is False


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestJobModels:
    def test_job_status_enum(self):
        assert JobStatus.PENDING == "pending"
        assert JobStatus.COMPLETED == "completed"

    def test_job_operation_enum(self):
        assert JobOperation.EVALUATE == "evaluate"
        assert JobOperation.AGING == "aging"
