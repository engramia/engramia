# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Failure clustering engine.

Groups recurring failures by similarity to identify systemic issues.
Uses word-level Jaccard similarity (no embedding dependency) for clustering.

Each cluster represents a category of failure (e.g. "agent fails on XML parsing",
"timeout on large files"). Surfacing clusters helps prioritize fixes.
"""

import logging
import re

from engramia._util import jaccard
from engramia.core.eval_feedback import EvalFeedbackStore

_log = logging.getLogger(__name__)

_CLUSTER_THRESHOLD = 0.4  # Jaccard threshold for grouping failures (matches eval_feedback.py)


class FailureCluster:
    """A group of similar failure patterns.

    Attributes:
        representative: The most common feedback string in the cluster.
        members: All feedback strings in the cluster.
        total_count: Sum of occurrence counts across all members.
        avg_score: Average relevance score across members.
    """

    def __init__(
        self,
        representative: str,
        members: list[str],
        total_count: int,
        avg_score: float,
    ) -> None:
        self.representative = representative
        self.members = members
        self.total_count = total_count
        self.avg_score = avg_score

    def __repr__(self) -> str:
        return (
            f"FailureCluster(representative={self.representative!r}, "
            f"members={len(self.members)}, total_count={self.total_count})"
        )


class FailureClusterer:
    """Clusters failure patterns from the feedback store.

    Args:
        feedback_store: Feedback store to read failure patterns from.
    """

    def __init__(self, feedback_store: EvalFeedbackStore) -> None:
        self._feedback_store = feedback_store

    def analyze(self, min_count: int = 1) -> list[FailureCluster]:
        """Cluster failure patterns by similarity.

        Args:
            min_count: Minimum occurrence count for a pattern to be included.

        Returns:
            List of FailureCluster objects sorted by total_count descending.
        """
        raw = self._feedback_store._load_raw()
        patterns = [p for p in raw if p.get("count", 0) >= min_count]

        if not patterns:
            return []

        clusters: list[dict] = []

        for pattern in patterns:
            text = pattern["pattern"]
            norm = _normalize(text)
            merged = False

            for cluster in clusters:
                if jaccard(_normalize(cluster["representative"]), norm) > _CLUSTER_THRESHOLD:
                    cluster["members"].append(text)
                    cluster["total_count"] += pattern.get("count", 1)
                    cluster["scores"].append(pattern.get("score", 0.5))
                    merged = True
                    break

            if not merged:
                clusters.append(
                    {
                        "representative": text,
                        "members": [text],
                        "total_count": pattern.get("count", 1),
                        "scores": [pattern.get("score", 0.5)],
                    }
                )

        result = []
        for c in clusters:
            avg_score = sum(c["scores"]) / len(c["scores"]) if c["scores"] else 0.0
            result.append(
                FailureCluster(
                    representative=c["representative"],
                    members=c["members"],
                    total_count=c["total_count"],
                    avg_score=round(avg_score, 4),
                )
            )

        result.sort(key=lambda c: c.total_count, reverse=True)
        return result


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
