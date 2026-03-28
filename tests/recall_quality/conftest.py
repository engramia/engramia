# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Pytest fixtures for the recall quality test suite.

Supports two execution modes controlled by ENGRAMIA_TEST_MODE env var:
  - local  (default): JSONStorage + sentence-transformers — no API keys needed
  - remote           : EngramiaWebhook → production REST API

All test tasks are prefixed with a unique run_id so they can be identified
and cleaned up without polluting shared storage.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

import pytest

_THRESHOLDS_PATH = Path(__file__).parent / "thresholds.json"
_RESULTS_DIR = Path(__file__).parent / "results"


# ---------------------------------------------------------------------------
# QualityTracker — longitudinal metric collection
# ---------------------------------------------------------------------------


class QualityTracker:
    """Collects per-dimension recall quality metrics for one test session.

    Fixtures in D1–D3 and boundary tests call record_*() to feed data.
    On session teardown the tracker writes a timestamped JSON file to
    tests/recall_quality/results/ so quality trends can be monitored
    across code changes and embedding model upgrades.
    """

    def __init__(self) -> None:
        self._d1: list[dict] = []
        self._d2: list[dict] = []
        self._d3: dict | None = None
        self._boundary: list[dict] = []

    # -- record helpers -------------------------------------------------------

    def record_d1(self, cluster_id: str, top1_sim: float, passed: bool) -> None:
        self._d1.append({"cluster": cluster_id, "top1_sim": round(top1_sim, 4), "pass": passed})

    def record_d2(self, cluster_a: str, cluster_b: str, max_cross_sim: float, passed: bool) -> None:
        self._d2.append({
            "pair": f"{cluster_a}_{cluster_b}",
            "max_cross_sim": round(max_cross_sim, 4),
            "pass": passed,
        })

    def record_d3(self, noise_total: int, noise_failed: int, max_noise_sim: float) -> None:
        self._d3 = {
            "noise_total": noise_total,
            "noise_failed": noise_failed,
            "max_noise_sim": round(max_noise_sim, 4),
            "pass": noise_failed == 0,
        }

    def record_boundary(self, task: str, matched_a: bool, matched_b: bool, passed: bool) -> None:
        self._boundary.append({
            "task": task[:70],
            "matched_a": matched_a,
            "matched_b": matched_b,
            "pass": passed,
        })

    # -- build / save ---------------------------------------------------------

    def build(self, thresholds: dict) -> dict:
        """Assemble the full metrics dict for this session."""
        try:
            git_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            git_hash = "unknown"

        try:
            git_branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            git_branch = "unknown"

        ts = datetime.now(timezone.utc)
        run_id = f"{ts.strftime('%Y%m%dT%H%M%S')}_{git_hash}"

        # D1 aggregates
        d1_sims = [r["top1_sim"] for r in self._d1]
        d1 = {
            "pass": all(r["pass"] for r in self._d1) if self._d1 else None,
            "clusters_total": len(self._d1),
            "clusters_passed": sum(1 for r in self._d1 if r["pass"]),
            "avg_top1_sim": round(sum(d1_sims) / len(d1_sims), 4) if d1_sims else None,
            "min_top1_sim": round(min(d1_sims), 4) if d1_sims else None,
            "per_cluster": {r["cluster"]: {"top1_sim": r["top1_sim"], "pass": r["pass"]} for r in self._d1},
        }

        # D2 aggregates
        d2_sims = [r["max_cross_sim"] for r in self._d2]
        d2 = {
            "pass": all(r["pass"] for r in self._d2) if self._d2 else None,
            "pairs_total": len(self._d2),
            "pairs_passed": sum(1 for r in self._d2 if r["pass"]),
            "max_cross_sim": round(max(d2_sims), 4) if d2_sims else None,
            "per_pair": {r["pair"]: {"max_cross_sim": r["max_cross_sim"], "pass": r["pass"]} for r in self._d2},
        }

        # D3
        d3 = self._d3 or {"pass": None, "noise_total": 0, "noise_failed": 0, "max_noise_sim": None}

        # Boundary
        boundary = {
            "pass": all(r["pass"] for r in self._boundary) if self._boundary else None,
            "tasks_total": len(self._boundary),
            "matched_either": sum(1 for r in self._boundary if r["pass"]),
            "matched_both": sum(1 for r in self._boundary if r["matched_a"] and r["matched_b"]),
            "per_task": self._boundary,
        }

        return {
            "run_id": run_id,
            "timestamp": ts.isoformat(),
            "git_commit": git_hash,
            "git_branch": git_branch,
            "embedding_model": thresholds.get("_model", "unknown"),
            "thresholds": {
                "intra": thresholds.get("intra_threshold"),
                "cross": thresholds.get("cross_threshold"),
                "noise": thresholds.get("noise_threshold"),
            },
            "dimensions": {
                "D1_recall_precision": d1,
                "D2_cross_isolation": d2,
                "D3_noise_rejection": d3,
                "boundary": boundary,
            },
        }

    def save(self, thresholds: dict, results_dir: Path) -> Path | None:
        """Write metrics to results_dir/{run_id}.json. Returns path or None."""
        has_data = bool(self._d1 or self._d2 or self._d3 or self._boundary)
        if not has_data:
            return None
        data = self.build(thresholds)
        results_dir.mkdir(parents=True, exist_ok=True)
        out = results_dir / f"{data['run_id']}.json"
        out.write_text(json.dumps(data, indent=2))
        return out


# ---------------------------------------------------------------------------
# Normalised match dict helpers
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

    def find_by_skills(
        self, required: list[str], match_all: bool = True
    ) -> list[dict]:
        raw = self._b.find_by_skills(required=required, match_all=match_all)
        return [_normalise_match(m) for m in raw]

    @property
    def raw(self) -> Any:
        """Access underlying backend (Memory or EngramiaWebhook)."""
        return self._b


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def run_tag() -> str:
    """Unique tag for this test session — prefixed on all task strings."""
    return f"RQ-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def quality_tracker(thresholds) -> Generator[QualityTracker, None, None]:
    """Session-scoped collector for recall quality metrics.

    Yields a QualityTracker that quality tests populate via record_*() calls.
    On session teardown writes a timestamped JSON run file to
    tests/recall_quality/results/ for longitudinal trend analysis.
    """
    tracker = QualityTracker()
    yield tracker
    saved = tracker.save(thresholds, _RESULTS_DIR)
    if saved:
        print(f"\n  Quality metrics → {saved.relative_to(Path(__file__).parent.parent.parent)}")


@pytest.fixture(scope="session")
def thresholds() -> dict:
    """Load similarity thresholds (from calibrate.py output or defaults)."""
    if _THRESHOLDS_PATH.exists():
        return json.loads(_THRESHOLDS_PATH.read_text())
    return {
        "intra_threshold": 0.55,
        "cross_threshold": 0.50,
        "noise_threshold": 0.50,
    }


@pytest.fixture(scope="session")
def client(tmp_path_factory, run_tag):  # noqa: F811
    """Session-scoped TestClient in local or remote mode."""
    mode = os.environ.get("ENGRAMIA_TEST_MODE", "local").lower()

    if mode == "remote":
        api_url = os.environ.get("ENGRAMIA_API_URL")
        if not api_url:
            pytest.skip("ENGRAMIA_API_URL not set — skipping remote tests")
        from engramia.sdk.webhook import EngramiaWebhook

        backend = EngramiaWebhook(
            url=api_url,
            api_key=os.environ.get("ENGRAMIA_API_KEY"),
        )
        return TestClient(backend, mode="remote")

    # Local mode — isolated tmp storage per session
    from engramia import Memory
    from engramia.providers import JSONStorage
    from engramia.providers.local_embeddings import LocalEmbeddings

    tmp = tmp_path_factory.mktemp("engramia_rq")
    backend = Memory(
        embeddings=LocalEmbeddings(),
        storage=JSONStorage(path=tmp),
    )
    return TestClient(backend, mode="local")


# ---------------------------------------------------------------------------
# Helpers for per-test learn+discover_key+cleanup
# ---------------------------------------------------------------------------

def learn_and_get_key(
    client: TestClient,
    task: str,
    code: str,
    eval_score: float,
    output: str | None = None,
) -> str:
    """Learn a pattern and immediately recall to discover its storage key.

    Returns:
        pattern_key string, or "" if recall returned nothing.
    """
    client.learn(task=task, code=code, eval_score=eval_score, output=output)
    # Small pause helps in remote mode where pgvector may have slight indexing lag
    if os.environ.get("ENGRAMIA_TEST_MODE", "local").lower() == "remote":
        time.sleep(0.15)
    matches = client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)
    if matches:
        return matches[0]["pattern_key"]
    return ""
