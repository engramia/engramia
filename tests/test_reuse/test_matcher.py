# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Unit tests for PatternMatcher (eval-weighted semantic search)."""

from engramia.core.eval_store import EvalStore
from engramia.reuse.matcher import PatternMatcher
from engramia.types import Pattern


class TestPatternMatcher:
    """Tests for PatternMatcher.find()."""

    def _store_pattern(self, storage, embeddings, task, code="pass", score=8.0):
        """Helper: store a pattern + embedding under a patterns/ key."""
        import hashlib
        import time

        h = hashlib.md5(task.encode()).hexdigest()[:8]
        key = f"patterns/{h}_{int(time.time() * 1000)}"
        pattern = Pattern(task=task, design={"code": code}, success_score=score)
        storage.save(key, pattern.model_dump())
        storage.save_embedding(key, embeddings.embed(task))
        return key

    def test_find_returns_matches(self, storage, fake_embeddings):
        eval_store = EvalStore(storage)
        self._store_pattern(storage, fake_embeddings, "Parse CSV file")

        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        matches = matcher.find("Parse CSV file", limit=5)

        assert len(matches) >= 1
        assert matches[0].similarity > 0.5
        assert matches[0].pattern.task == "Parse CSV file"
        assert matches[0].pattern_key.startswith("patterns/")

    def test_find_empty_storage(self, storage, fake_embeddings):
        eval_store = EvalStore(storage)
        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        matches = matcher.find("anything", limit=5)
        assert matches == []

    def test_find_respects_limit(self, storage, fake_embeddings):
        eval_store = EvalStore(storage)
        for i in range(5):
            self._store_pattern(storage, fake_embeddings, f"Task number {i}", score=7.0 + i * 0.1)

        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        matches = matcher.find("Task number 2", limit=2)
        assert len(matches) <= 2

    def test_find_applies_eval_weighting(self, storage, fake_embeddings):
        eval_store = EvalStore(storage)
        key = self._store_pattern(storage, fake_embeddings, "Compute statistics")

        # Store a high eval score for the pattern
        eval_store.save(agent_name=key, task="Compute statistics", scores={"overall": 9.5})

        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        matches = matcher.find("Compute statistics", limit=5)
        assert len(matches) >= 1
        # With a high eval score, the multiplier should be close to 1.0
        assert matches[0].similarity > 0.5

    def test_find_assigns_reuse_tier(self, storage, fake_embeddings):
        eval_store = EvalStore(storage)
        self._store_pattern(storage, fake_embeddings, "Parse CSV exactly")

        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        # Exact same task -> should be duplicate tier
        matches = matcher.find("Parse CSV exactly", limit=5)
        assert len(matches) >= 1
        assert matches[0].reuse_tier == "duplicate"

    def test_find_skips_corrupted_pattern(self, storage, fake_embeddings):
        eval_store = EvalStore(storage)
        # Store a corrupted pattern (missing required fields)
        key = "patterns/corrupted_123"
        storage.save(key, {"invalid": "data"})
        storage.save_embedding(key, fake_embeddings.embed("corrupted"))

        # Store a valid pattern
        self._store_pattern(storage, fake_embeddings, "Valid task")

        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        matches = matcher.find("Valid task", limit=5)
        # Should return only the valid pattern, skipping the corrupted one
        for m in matches:
            assert m.pattern.task == "Valid task"
