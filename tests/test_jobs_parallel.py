# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Regression tests: JobWorker dispatches claimed jobs in parallel.

Proves that when a ThreadPoolExecutor is passed to ``JobService.poll_and_execute``,
multiple claimed jobs run concurrently rather than serially. Without this, the
worker's ``max_concurrent`` knob is a lie (see audit finding T2-03).

Each parallel job must run in an isolated ``contextvars`` snapshot so that
scope/request_id set by one job is invisible to a sibling job.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from engramia._context import get_scope, reset_scope, set_scope
from engramia.jobs.models import JobStatus
from engramia.jobs.service import JobService
from engramia.types import Scope


@pytest.fixture(autouse=True)
def default_scope():
    token = set_scope(Scope(tenant_id="t", project_id="p"))
    yield
    reset_scope(token)


def test_two_jobs_run_concurrently_when_executor_provided():
    """Two jobs submitted to a 2-worker executor must pass a ``Barrier(2)`` —
    this is only possible if they actually execute on different threads."""
    svc = JobService(engine=None, memory=MagicMock())

    barrier = threading.Barrier(2, timeout=5.0)
    seen_threads: list[int] = []
    lock = threading.Lock()

    def fake_dispatch(memory, operation, params):
        # If execution is truly parallel, both threads meet at the barrier.
        # If serial, the second `wait()` would deadlock and time out.
        barrier.wait()
        with lock:
            seen_threads.append(threading.get_ident())
        return {"ok": True}

    # Submit two pending jobs directly to the in-memory store.
    svc.submit("aging", {})
    svc.submit("aging", {})

    # Monkey-patch the dispatcher used by _execute_job.
    import engramia.jobs.service as svc_mod

    original = svc_mod.dispatch_job
    svc_mod.dispatch_job = fake_dispatch
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            executed = svc.poll_and_execute(batch_size=2, executor=executor)
    finally:
        svc_mod.dispatch_job = original

    assert executed == 2
    assert len(seen_threads) == 2
    assert seen_threads[0] != seen_threads[1], "jobs ran on the same thread — serial execution"

    jobs = list(svc._mem_store.values())
    assert all(j["status"] == JobStatus.COMPLETED for j in jobs)


def test_parallel_jobs_have_isolated_scope():
    """Job A's set_scope must not leak into Job B when running in parallel."""
    svc = JobService(engine=None, memory=MagicMock())

    job_a_id = svc.submit("aging", {}).job_id
    job_b_id = svc.submit("aging", {}).job_id

    # Set distinct scopes on each stored job so we can verify they are
    # respected during parallel execution.
    svc._mem_store[job_a_id]["tenant_id"] = "tenant-A"
    svc._mem_store[job_a_id]["project_id"] = "proj-A"
    svc._mem_store[job_b_id]["tenant_id"] = "tenant-B"
    svc._mem_store[job_b_id]["project_id"] = "proj-B"

    barrier = threading.Barrier(2, timeout=5.0)
    observed: dict[str, Scope] = {}
    lock = threading.Lock()

    def fake_dispatch(memory, operation, params):
        # Force both threads to be in flight simultaneously before each
        # reads its own scope — so if context leaked, we'd see it.
        barrier.wait()
        scope = get_scope()
        with lock:
            observed[scope.tenant_id] = scope
        # Small sleep to make any context-leak race more likely to fail.
        time.sleep(0.05)
        return None

    import engramia.jobs.service as svc_mod

    original = svc_mod.dispatch_job
    svc_mod.dispatch_job = fake_dispatch
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            svc.poll_and_execute(batch_size=2, executor=executor)
    finally:
        svc_mod.dispatch_job = original

    assert set(observed.keys()) == {"tenant-A", "tenant-B"}
    assert observed["tenant-A"].project_id == "proj-A"
    assert observed["tenant-B"].project_id == "proj-B"


def test_serial_fallback_when_executor_is_none():
    """Without an executor, jobs still run — just serially on the caller."""
    svc = JobService(engine=None, memory=MagicMock())
    svc.submit("aging", {})
    svc.submit("aging", {})

    calls: list[int] = []

    def fake_dispatch(memory, operation, params):
        calls.append(threading.get_ident())
        return None

    import engramia.jobs.service as svc_mod

    original = svc_mod.dispatch_job
    svc_mod.dispatch_job = fake_dispatch
    try:
        executed = svc.poll_and_execute(batch_size=2, executor=None)
    finally:
        svc_mod.dispatch_job = original

    assert executed == 2
    # Serial execution — both jobs ran on the same (calling) thread.
    assert len(set(calls)) == 1
