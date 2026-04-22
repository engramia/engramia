# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for the quality-evidence path — the ranking-side counterpart to
survival-side reuse / aging tests.

Covers:

* ``Memory.refine_pattern(key, eval_score)`` — appends a new eval record
  and is immediately visible to ``eval_weighted`` recall.
* ``Memory.evaluate(..., pattern_key=...)`` — evaluation results flow
  into the eval store under the caller-supplied key, closing the learn
  → evaluate → recall loop. Without ``pattern_key``, the pre-0.6.8
  behaviour (SHA-256 of code) is preserved.
* Decoupling regression — ``mark_reused`` and direct
  ``Pattern.success_score`` mutations remain orthogonal to ranking, as
  documented in ``docs/concepts.md``.

These tests pin the mental model: **survival signals (reuse,
success_score, aging) are separate from ranking signals (eval_store-
driven multiplier, recency_weight)**. Regressing this separation would
change user-facing semantics.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engramia.exceptions import ValidationError
from engramia.memory import Memory


def _keys_for(mem: Memory, task: str) -> list[str]:
    """Storage keys whose stored task matches ``task`` exactly."""
    out = []
    for k in mem._storage.list_keys(prefix="patterns/"):  # noqa: SLF001
        data = mem._storage.load(k)
        if data and data.get("task") == task:
            out.append(k)
    return out


# ---------------------------------------------------------------------------
# refine_pattern
# ---------------------------------------------------------------------------


class TestRefinePattern:
    def test_refine_raises_on_unknown_key(self, mem):
        with pytest.raises(ValidationError, match="does not exist"):
            mem.refine_pattern("patterns/definitely_not_here", 7.0)

    def test_refine_validates_score_range(self, mem):
        mem.learn(task="Known", code="pass", eval_score=5.0)
        key = _keys_for(mem, "Known")[0]
        with pytest.raises(ValidationError, match="eval_score"):
            mem.refine_pattern(key, -0.1)
        with pytest.raises(ValidationError, match="eval_score"):
            mem.refine_pattern(key, 10.5)

    def test_refine_updates_eval_multiplier(self, mem):
        mem.learn(task="Known", code="pass", eval_score=5.0, on_duplicate="keep_both")
        key = _keys_for(mem, "Known")[0]
        before = mem._eval_store.get_eval_multiplier(key, "Known")  # noqa: SLF001
        # Score 5.0 → multiplier 0.5 + 0.5 * 0.5 = 0.75.
        assert before == pytest.approx(0.75)

        mem.refine_pattern(key, 9.5)
        after = mem._eval_store.get_eval_multiplier(key, "Known")  # noqa: SLF001
        # Score 9.5 → multiplier 0.5 + 0.5 * 0.95 = 0.975.
        assert after == pytest.approx(0.975)

    def test_refine_changes_eval_weighted_ranking(self, mem):
        # Two patterns with identical task text + initial score. Refine
        # one down, the other up. eval_weighted recall must reorder.
        mem.learn(task="Ranking probe", code="# A", eval_score=5.0, on_duplicate="keep_both")
        mem.learn(task="Ranking probe", code="# B", eval_score=5.0, on_duplicate="keep_both")
        keys = _keys_for(mem, "Ranking probe")
        assert len(keys) == 2, "test setup expects two independent patterns"

        # Designate the key with `# A` code as the high-quality one.
        a_key = next(k for k in keys if mem._storage.load(k)["design"]["code"] == "# A")
        b_key = next(k for k in keys if mem._storage.load(k)["design"]["code"] == "# B")

        mem.refine_pattern(a_key, 9.5)
        mem.refine_pattern(b_key, 1.0)

        matches = mem.recall(
            task="Ranking probe",
            limit=2,
            deduplicate=False,
            eval_weighted=True,
            readonly=True,
        )
        assert [m.pattern_key for m in matches] == [a_key, b_key], matches

    def test_refine_does_not_mutate_pattern_success_score(self, mem):
        # Survival (Pattern.success_score) and ranking (eval store) are
        # orthogonal. refine_pattern is a ranking operation.
        mem.learn(task="Check survival", code="pass", eval_score=5.0)
        key = _keys_for(mem, "Check survival")[0]
        before = mem._storage.load(key)["success_score"]

        mem.refine_pattern(key, 9.5)

        after = mem._storage.load(key)["success_score"]
        assert before == after, "refine_pattern must not touch Pattern.success_score"

    def test_refine_override_task_text(self, mem):
        mem.learn(task="Original task", code="pass", eval_score=5.0)
        key = _keys_for(mem, "Original task")[0]
        mem.refine_pattern(key, 8.0, task="External grading rubric variant", feedback="reads better")

        # The latest eval record's task field reflects the override, not
        # the stored pattern's task — for auditing what judgement context
        # produced the score.
        evals = mem._storage.load("evals/default/default/_list")  # noqa: SLF001
        matching = [e for e in evals if e["agent_name"] == key]
        assert matching, "expected a refine_pattern record"
        assert matching[-1]["task"] == "External grading rubric variant"
        assert matching[-1]["scores"]["feedback"] == "reads better"


# ---------------------------------------------------------------------------
# evaluate(pattern_key=...)
# ---------------------------------------------------------------------------


@pytest.fixture
def mem_with_llm(fake_embeddings, storage, mock_llm):
    return Memory(llm=mock_llm, embeddings=fake_embeddings, storage=storage)


class TestEvaluatePatternKey:
    def test_evaluate_without_pattern_key_uses_sha256(self, mem_with_llm):
        # Backward-compatible path: agent_name is sha256(code)[:12].
        mem_with_llm.evaluate(task="Task", code="def a(): pass", num_evals=1)
        evals = mem_with_llm._storage.load("evals/default/default/_list")  # noqa: SLF001
        assert evals, "expected an eval record"
        # Latest record: agent_name is a 12-char hex string.
        latest = evals[-1]
        assert len(latest["agent_name"]) == 12
        assert all(c in "0123456789abcdef" for c in latest["agent_name"])

    def test_evaluate_with_pattern_key_uses_it(self, mem_with_llm):
        mem_with_llm.learn(task="Checkout handler", code="def a(): pass", eval_score=5.0)
        key = _keys_for(mem_with_llm, "Checkout handler")[0]

        mem_with_llm.evaluate(
            task="Checkout handler",
            code="def a(): pass",
            num_evals=1,
            pattern_key=key,
        )

        evals = mem_with_llm._storage.load("evals/default/default/_list")  # noqa: SLF001
        # The LATEST eval record is tied to the real pattern key, not
        # a sha256 orphan.
        assert evals[-1]["agent_name"] == key

    def test_evaluate_with_pattern_key_flows_into_recall(self, mem_with_llm, mock_llm):
        # Seed two patterns, evaluate ONE of them to a lower score,
        # and verify recall demotes it.
        mem_with_llm.learn(task="Same task text", code="def a(): pass", eval_score=5.0, on_duplicate="keep_both")
        mem_with_llm.learn(task="Same task text", code="def b(): pass", eval_score=5.0, on_duplicate="keep_both")
        keys = _keys_for(mem_with_llm, "Same task text")

        a_key = next(k for k in keys if mem_with_llm._storage.load(k)["design"]["code"] == "def a(): pass")
        b_key = next(k for k in keys if mem_with_llm._storage.load(k)["design"]["code"] == "def b(): pass")

        # Mock the LLM to return a LOW score for pattern A.
        import json

        mock_llm.call.return_value = json.dumps({
            "task_alignment": 1,
            "code_quality": 1,
            "workspace_usage": 1,
            "robustness": 1,
            "overall": 1.5,
            "feedback": "low quality",
        })

        mem_with_llm.evaluate(
            task="Same task text",
            code="def a(): pass",
            num_evals=1,
            pattern_key=a_key,
        )

        # Recall: B should now rank above A.
        matches = mem_with_llm.recall(
            task="Same task text",
            limit=2,
            deduplicate=False,
            eval_weighted=True,
            readonly=True,
        )
        assert [m.pattern_key for m in matches] == [b_key, a_key]

    def test_evaluate_raises_on_unknown_pattern_key(self, mem_with_llm):
        with pytest.raises(ValidationError, match="does not exist"):
            mem_with_llm.evaluate(
                task="Task",
                code="def a(): pass",
                num_evals=1,
                pattern_key="patterns/definitely_not_here",
            )


# ---------------------------------------------------------------------------
# Decoupling regression — survival path stays orthogonal to ranking.
# ---------------------------------------------------------------------------


class TestDecouplingRegression:
    """Pin the intentional decoupling between survival signals
    (``mark_reused`` boost, direct ``success_score`` edits,
    ``run_aging`` decay) and ranking signals (eval_store multiplier,
    recency_weight).

    Breaking these assertions should be a conscious design decision, not
    an accident.
    """

    def test_mark_reused_does_not_change_ranking(self, mem):
        mem.learn(task="Same text", code="# A", eval_score=5.0, on_duplicate="keep_both")
        mem.learn(task="Same text", code="# B", eval_score=5.0, on_duplicate="keep_both")
        keys = _keys_for(mem, "Same text")
        a_key = next(k for k in keys if mem._storage.load(k)["design"]["code"] == "# A")
        b_key = next(k for k in keys if mem._storage.load(k)["design"]["code"] == "# B")

        for _ in range(20):
            mem._pattern_store.mark_reused(a_key)  # noqa: SLF001

        matches = mem.recall(
            task="Same text",
            limit=2,
            deduplicate=False,
            eval_weighted=True,
            readonly=True,
        )
        # Both patterns have the same eval record (5.0) → same multiplier,
        # same similarity → same effective_score. The returned order is
        # driven by storage iteration, NOT by reuse boost.
        assert len({m.effective_score for m in matches}) == 1, (
            f"mark_reused must not change effective_score; got {[m.effective_score for m in matches]}"
        )
        # And the reuse boost must still have taken effect on survival:
        assert mem._storage.load(a_key)["reuse_count"] == 20  # noqa: SLF001

    def test_direct_success_score_edit_does_not_change_ranking(self, mem):
        mem.learn(task="Survival edit", code="# X", eval_score=5.0, on_duplicate="keep_both")
        mem.learn(task="Survival edit", code="# Y", eval_score=5.0, on_duplicate="keep_both")
        keys = _keys_for(mem, "Survival edit")
        boosted_key = keys[0]

        data = mem._storage.load(boosted_key)
        data["success_score"] = 9.5
        mem._storage.save(boosted_key, data)  # noqa: SLF001

        matches = mem.recall(
            task="Survival edit",
            limit=2,
            deduplicate=False,
            eval_weighted=True,
            readonly=True,
        )
        assert len({m.effective_score for m in matches}) == 1, (
            "raw Pattern.success_score edits are survival-path only; must not affect ranking"
        )
