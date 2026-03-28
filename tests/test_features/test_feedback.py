# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D9 — Feedback lifecycle.

EvalFeedbackStore requires count >= 2 to surface feedback.
Tests:
  1. Single feedback entry → NOT surfaced (count < 2).
  2. Three similar feedback entries (Jaccard > 0.4) → clustered, count=3, surfaced.
  3. run_feedback_decay() → score decreases.
  4. Completely different feedback × 1 → NOT surfaced.

Note: feedback storage is shared (not namespaced by run_id).
Tests use distinctive phrases to avoid collision with real production data.
"""
from __future__ import annotations

import pytest

from tests.recall_quality.conftest import TestClient

# Three variants with high Jaccard overlap (>0.4) — will cluster together
_FEEDBACK_REPEATED = [
    "RQ_TEST: missing error handling for file operations edge cases",
    "RQ_TEST: no error handling in file operation edge cases present",
    "RQ_TEST: missing error handling for edge cases in file operations",
]

# Unique one-off feedback — should NOT surface
_FEEDBACK_ONEOFF = "RQ_TEST_UNIQUE_abc123: extremely specific one-time feedback pattern xyz"


def test_single_feedback_not_surfaced(client: TestClient) -> None:
    """A feedback string recorded only once should not appear in get_feedback()."""
    # The EvalFeedbackStore uses a shared singleton key — we can only observe, not reset.
    # We use a unique phrase guaranteed not to match anything else.
    unique = f"RQ_ONCEONLY_{id(object())}: unique irreproducible feedback phrase"

    if hasattr(client.raw, "get_feedback"):
        # Local mode: direct access to feedback store
        client.raw._feedback_store.record(unique)
        feedback = client.get_feedback(limit=20)
    else:
        # Remote: we can't inject feedback directly without /evaluate
        pytest.skip("Cannot inject feedback directly in remote mode")

    assert unique not in feedback, (
        f"Feedback with count=1 was surfaced in get_feedback() — should require count>=2"
    )


def test_repeated_feedback_surfaces(client: TestClient) -> None:
    """Feedback recorded 3 times (with Jaccard>0.4 variants) should appear."""
    if not hasattr(client.raw, "_feedback_store"):
        pytest.skip("Requires direct feedback_store access — local mode only")

    store = client.raw._feedback_store

    # Record 3 variants — they should cluster (Jaccard > 0.4)
    for fb in _FEEDBACK_REPEATED:
        store.record(fb)

    feedback = client.get_feedback(limit=20)
    found = any("RQ_TEST" in f and "missing error handling" in f for f in feedback)
    assert found, (
        f"Repeated feedback (count=3) not found in get_feedback().\n"
        f"Returned: {feedback[:5]}"
    )


def test_feedback_decay_reduces_score(client: TestClient) -> None:
    """run_feedback_decay() should reduce feedback pattern scores."""
    if not hasattr(client.raw, "_feedback_store"):
        pytest.skip("Requires direct feedback_store access — local mode only")

    store = client.raw._feedback_store

    # Ensure there's at least one feedback entry with count>=2 before decay
    for fb in _FEEDBACK_REPEATED:
        store.record(fb)

    # Get raw score before decay
    raw_before = store._load_raw()
    rq_entries_before = [
        p for p in raw_before
        if "RQ_TEST" in p.get("pattern", "") and p.get("count", 0) >= 2
    ]
    if not rq_entries_before:
        pytest.skip("No suitable feedback entries to test decay")

    score_before = rq_entries_before[0]["score"]

    # Run decay — patches last_decayed to force decay calculation
    import datetime
    import time
    _ONE_WEEK = 7 * 24 * 3600
    raw_entries = store._load_raw()
    for p in raw_entries:
        if "RQ_TEST" in p.get("pattern", ""):
            # Make it appear 2 weeks old
            old_ts = time.time() - 2 * _ONE_WEEK
            p["last_decayed"] = datetime.datetime.fromtimestamp(
                old_ts, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S")
    store._storage.save("feedback/_list", raw_entries)

    client.run_feedback_decay()

    raw_after = store._load_raw()
    rq_entries_after = [
        p for p in raw_after
        if "RQ_TEST" in p.get("pattern", "") and p.get("count", 0) >= 2
    ]

    if rq_entries_after:
        score_after = rq_entries_after[0]["score"]
        assert score_after < score_before, (
            f"Feedback score did not decrease after decay: "
            f"before={score_before:.4f}, after={score_after:.4f}"
        )


def test_oneoff_feedback_not_surfaced(client: TestClient) -> None:
    """A one-time feedback string should not appear in get_feedback()."""
    if not hasattr(client.raw, "_feedback_store"):
        pytest.skip("Requires direct feedback_store access — local mode only")

    store = client.raw._feedback_store
    store.record(_FEEDBACK_ONEOFF)

    feedback = client.get_feedback(limit=20)
    assert _FEEDBACK_ONEOFF not in feedback, (
        "One-off feedback was surfaced — get_feedback() should require count>=2"
    )
