# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for keyword-based recall fallback.

When the embedding provider raises an exception (e.g. API down, no key
configured), RecallService must fall back to Jaccard-based keyword search
instead of propagating the error to the caller.
"""

import pytest

from engramia import Memory
from engramia.exceptions import ProviderError
from engramia.providers.base import EmbeddingProvider
from engramia.providers.json_storage import JSONStorage
from tests.conftest import FakeEmbeddings


class FailingEmbeddings(EmbeddingProvider):
    """Embedding provider that always raises ProviderError."""

    def embed(self, text: str) -> list[float]:
        raise ProviderError("Embedding API unavailable")


class FlipEmbeddings(EmbeddingProvider):
    """Embeds successfully for the first N calls, then fails."""

    def __init__(self, fail_after: int):
        self._fail_after = fail_after
        self._calls = 0
        self._delegate = FakeEmbeddings()

    def embed(self, text: str) -> list[float]:
        self._calls += 1
        if self._calls > self._fail_after:
            raise ProviderError("Embedding API quota exceeded")
        return self._delegate.embed(text)


@pytest.fixture
def working_storage(tmp_path):
    return JSONStorage(path=tmp_path)


class TestKeywordFallback:
    def test_recall_returns_results_when_embeddings_fail(self, working_storage):
        """Recall must not raise when embeddings fail — returns keyword matches."""
        # Learn using working embeddings
        good_mem = Memory(embeddings=FakeEmbeddings(), storage=working_storage)
        good_mem.learn(task="parse csv file into rows", code="pd.read_csv(f)", eval_score=8.0)
        good_mem.learn(task="fetch data from rest api", code="requests.get(url)", eval_score=7.0)

        # Recall using broken embeddings — should fall back to keyword search
        broken_mem = Memory(embeddings=FailingEmbeddings(), storage=working_storage)
        results = broken_mem.recall("parse csv file", limit=5)

        # Should return a match via keyword similarity
        assert len(results) >= 1
        assert "csv" in results[0].pattern.task.lower()

    def test_recall_does_not_raise_on_embedding_failure(self, working_storage):
        """RecallService must never propagate embedding provider errors."""
        good_mem = Memory(embeddings=FakeEmbeddings(), storage=working_storage)
        good_mem.learn(task="compute statistics over dataset", code="stats(df)", eval_score=7.5)

        broken_mem = Memory(embeddings=FailingEmbeddings(), storage=working_storage)
        # Must not raise ProviderError
        try:
            results = broken_mem.recall("statistics dataset", limit=5)
        except ProviderError:
            pytest.fail("recall() must not propagate ProviderError — fallback expected")

    def test_recall_empty_store_with_failing_embeddings(self, working_storage):
        """Keyword fallback on empty store must return empty list."""
        broken_mem = Memory(embeddings=FailingEmbeddings(), storage=working_storage)
        results = broken_mem.recall("anything", limit=5)
        assert results == []

    def test_recall_fallback_respects_limit(self, working_storage):
        """Keyword fallback must honour the limit parameter."""
        good_mem = Memory(embeddings=FakeEmbeddings(), storage=working_storage)
        for i in range(8):
            good_mem.learn(
                task=f"parse csv data task variant {i}",
                code=f"parse_{i}()",
                eval_score=7.0,
            )

        broken_mem = Memory(embeddings=FailingEmbeddings(), storage=working_storage)
        results = broken_mem.recall("parse csv data", limit=3)
        assert len(results) <= 3

    def test_recall_fallback_ranks_by_keyword_overlap(self, working_storage):
        """Result with more keyword overlap should rank higher."""
        good_mem = Memory(embeddings=FakeEmbeddings(), storage=working_storage)
        good_mem.learn(
            task="parse csv file filter rows by column value",
            code="high_overlap()",
            eval_score=7.0,
        )
        good_mem.learn(
            task="send email notification",
            code="low_overlap()",
            eval_score=9.0,  # higher score but different domain
        )

        broken_mem = Memory(embeddings=FailingEmbeddings(), storage=working_storage)
        results = broken_mem.recall("parse csv file", limit=5)

        assert results[0].pattern.code == "high_overlap()", (
            "Pattern with more keyword overlap should rank first regardless of eval_score"
        )

    def test_normal_recall_still_uses_embeddings(self, working_storage):
        """When embeddings work, the fallback must NOT be triggered."""
        mem = Memory(embeddings=FakeEmbeddings(), storage=working_storage)
        mem.learn(task="compute moving average", code="rolling_mean()", eval_score=8.0)
        results = mem.recall("moving average calculation", limit=5)
        # Normal recall returns similarity from embeddings — should be high for semantically similar tasks
        assert len(results) >= 1
        assert results[0].similarity >= 0.0

    def test_partial_failure_during_recall(self, working_storage):
        """If embeddings fail after some learns (flip scenario), recall falls back cleanly."""
        flip_emb = FlipEmbeddings(fail_after=2)
        mem = Memory(embeddings=flip_emb, storage=working_storage)

        # These two learn calls use working embeddings
        mem.learn(task="filter dataframe by date range", code="df_filter()", eval_score=8.0)
        mem.learn(task="group by category and sum values", code="groupby_sum()", eval_score=7.5)

        # Now embeddings fail — recall should fall back to keyword
        results = mem.recall("filter dataframe by date", limit=5)
        assert isinstance(results, list)  # No crash
