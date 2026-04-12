# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared test helpers used across recall_quality and test_features suites.

Provides a unified TestClient adapter that normalises the Memory and
EngramiaWebhook interfaces to a single API for use in quality and feature
tests.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Normalised match dict helper
# ---------------------------------------------------------------------------


def _normalise_match(m: Any) -> dict:
    """Convert a Match object or webhook dict into a consistent flat dict."""
    if isinstance(m, dict):
        # Webhook MatchOut — pattern.code is already flat
        return {
            "similarity": m.get("similarity", 0.0),
            "reuse_tier": m.get("reuse_tier", "fresh"),
            "pattern_key": m.get("pattern_key", ""),
            "pattern": {
                "task": m.get("pattern", {}).get("task", ""),
                "code": m.get("pattern", {}).get("code"),
                "success_score": m.get("pattern", {}).get("success_score", 0.0),
                "reuse_count": m.get("pattern", {}).get("reuse_count", 0),
            },
        }
    else:
        # Memory Match object
        return {
            "similarity": float(m.similarity),
            "reuse_tier": m.reuse_tier,
            "pattern_key": m.pattern_key,
            "pattern": {
                "task": m.pattern.task,
                "code": m.pattern.design.get("code") if m.pattern.design else None,
                "success_score": float(m.pattern.success_score),
                "reuse_count": int(m.pattern.reuse_count),
            },
        }


# ---------------------------------------------------------------------------
# TestClient
# ---------------------------------------------------------------------------


class TestClient:
    """Thin adapter that normalises Memory and EngramiaWebhook to one interface."""

    def __init__(self, backend: Any, *, mode: str = "local") -> None:
        self._b = backend
        self.mode = mode

    def learn(
        self,
        task: str,
        code: str,
        eval_score: float,
        output: str | None = None,
    ) -> dict:
        result = self._b.learn(task=task, code=code, eval_score=eval_score, output=output)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result if isinstance(result, dict) else {}

    def recall(
        self,
        task: str,
        limit: int = 5,
        deduplicate: bool = True,
        eval_weighted: bool = True,
    ) -> list[dict]:
        raw = self._b.recall(
            task=task,
            limit=limit,
            deduplicate=deduplicate,
            eval_weighted=eval_weighted,
        )
        return [_normalise_match(m) for m in raw]

    def delete_pattern(self, pattern_key: str) -> bool:
        result = self._b.delete_pattern(pattern_key)
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            return result.get("deleted", False)
        return False

    def run_aging(self) -> int:
        result = self._b.run_aging()
        if isinstance(result, dict):
            return result.get("pruned", 0)
        return int(result)

    def run_feedback_decay(self) -> int:
        result = self._b.run_feedback_decay()
        if isinstance(result, dict):
            return result.get("pruned", 0)
        return int(result)

    def get_feedback(self, task_type: str | None = None, limit: int = 5) -> list[str]:
        # Memory uses get_feedback(); webhook uses feedback()
        if hasattr(self._b, "get_feedback"):
            return self._b.get_feedback(task_type=task_type, limit=limit)
        return self._b.feedback(task_type=task_type, limit=limit)

    def register_skills(self, pattern_key: str, skills: list[str]) -> None:
        self._b.register_skills(pattern_key, skills)

    def find_by_skills(self, required: list[str], match_all: bool = True) -> list[dict]:
        raw = self._b.find_by_skills(required=required, match_all=match_all)
        return [_normalise_match(m) for m in raw]

    @property
    def raw(self) -> Any:
        """Access underlying backend (Memory or EngramiaWebhook)."""
        return self._b
