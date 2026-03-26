"""Tests for FailureClusterer."""

import pytest

from engramia.core.eval_feedback import EvalFeedbackStore
from engramia.evolution.failure_cluster import FailureClusterer


@pytest.fixture
def feedback_store(storage):
    return EvalFeedbackStore(storage)


class TestFailureClusterer:
    """Tests for failure clustering engine."""

    def test_empty_feedback_returns_empty(self, feedback_store):
        clusterer = FailureClusterer(feedback_store)
        clusters = clusterer.analyze()
        assert clusters == []

    def test_single_feedback_single_cluster(self, feedback_store):
        feedback_store.record("Add error handling for file operations")
        clusterer = FailureClusterer(feedback_store)
        clusters = clusterer.analyze(min_count=1)
        assert len(clusters) == 1
        assert clusters[0].total_count == 1

    def test_similar_feedback_merged(self, feedback_store):
        # Record similar feedback that should cluster together
        feedback_store.record("Add error handling for file operations")
        feedback_store.record("Add error handling for file I/O operations")
        feedback_store.record("Include error handling for file read operations")

        clusterer = FailureClusterer(feedback_store)
        clusters = clusterer.analyze(min_count=1)
        # Similar feedback should be merged into fewer clusters
        assert len(clusters) <= 2

    def test_different_feedback_separate_clusters(self, feedback_store):
        feedback_store.record("Handle timeout errors in API calls")
        feedback_store.record("Validate CSV column headers before parsing")

        clusterer = FailureClusterer(feedback_store)
        clusters = clusterer.analyze(min_count=1)
        assert len(clusters) == 2

    def test_sorted_by_count(self, feedback_store):
        # Create one issue that appears many times
        for _ in range(5):
            feedback_store.record("Missing input validation")
        # And one that appears once
        feedback_store.record("Unrelated different issue entirely new topic")

        clusterer = FailureClusterer(feedback_store)
        clusters = clusterer.analyze(min_count=1)
        assert len(clusters) >= 1
        # First cluster should have the highest count
        if len(clusters) > 1:
            assert clusters[0].total_count >= clusters[1].total_count

    def test_min_count_filter(self, feedback_store):
        feedback_store.record("One-time issue")
        clusterer = FailureClusterer(feedback_store)

        # With min_count=2, the single-occurrence feedback should be excluded
        clusters = clusterer.analyze(min_count=2)
        assert clusters == []
