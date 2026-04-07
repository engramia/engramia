# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for B4 (feedback length limit) and B5 (_parse_iso empty string)."""

import pytest

from engramia.core.eval_feedback import EvalFeedbackStore, _parse_iso


class TestFeedbackLengthLimit:
    def test_record_rejects_too_long(self, storage):
        store = EvalFeedbackStore(storage)
        with pytest.raises(ValueError, match="5000"):
            store.record("x" * 5001)

    def test_record_accepts_at_limit(self, storage):
        store = EvalFeedbackStore(storage)
        store.record("x" * 5000)  # should not raise

    def test_record_accepts_normal(self, storage):
        store = EvalFeedbackStore(storage)
        store.record("Always add error handling for file I/O.")  # should not raise


class TestParseIso:
    def test_empty_string_returns_recent_timestamp(self):
        import time

        ts = _parse_iso("")
        # Should be close to now (within 5 seconds)
        assert abs(ts - time.time()) < 5

    def test_valid_iso_parses_correctly(self):
        ts = _parse_iso("2024-01-15T12:00:00")
        assert ts > 0

    def test_malformed_returns_current_time(self):
        import time
        ts = _parse_iso("not-a-date")
        assert abs(ts - time.time()) < 5
