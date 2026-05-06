# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pin the ``FOR UPDATE SKIP LOCKED`` SQL contract on the job-claim path.

The Postgres parallelism tests use ``engine=None`` (in-memory store) and
the postgres-marked integration tests are auto-skipped without
testcontainers, so neither exercises the actual DB-mode claim SQL. The
claim's correctness rests entirely on the ``FOR UPDATE SKIP LOCKED``
clause: without it, two workers polling concurrently would either block
on row locks (no SKIP LOCKED) or claim duplicates (no FOR UPDATE).

Substring inspection is the right tool here because **the SQL clause IS
the contract** — there is no observable behavior in the in-memory or
mocked path that distinguishes "atomic claim" from "race-prone claim".
"""

from __future__ import annotations

from unittest.mock import MagicMock


def test_db_poll_and_execute_uses_for_update_skip_locked():
    """Direct contract pin on the claim SQL.

    A regression that drops ``FOR UPDATE SKIP LOCKED`` (or replaces it
    with a plain ``FOR UPDATE``) would not be caught by the in-memory
    parallelism tests and would only surface in production as duplicate
    job execution under load.
    """
    from engramia.jobs.service import JobService

    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.return_value.fetchall.return_value = []  # empty queue

    service = JobService(memory=MagicMock(), engine=engine)
    service._db_poll_and_execute(batch_size=5, executor=None)

    assert conn.execute.call_count == 1
    sql = str(conn.execute.call_args[0][0]).upper()

    # The atomicity contract — both keywords are required. A single
    # missing word would cause concurrent workers to block (without
    # SKIP LOCKED) or claim duplicates (without FOR UPDATE).
    assert "FOR UPDATE" in sql, (
        f"Job-claim SQL must use FOR UPDATE for row-level locking; got:\n{sql}"
    )
    assert "SKIP LOCKED" in sql, (
        f"Job-claim SQL must use SKIP LOCKED so concurrent workers don't "
        f"block on each other; got:\n{sql}"
    )

    # The batch size must be bound — without it a hot-loop poller can
    # accidentally claim every pending job at once and starve other
    # workers.
    assert "LIMIT :BATCH" in sql, (
        f"Job-claim SQL must bind the batch size; got:\n{sql}"
    )

    params = conn.execute.call_args[0][1]
    assert params == {"batch": 5}
