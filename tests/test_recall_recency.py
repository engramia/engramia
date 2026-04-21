# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for recency-weighted recall (``Memory.recall(recency_weight=...)``).

Covers:
- Validators on ``recency_weight`` and ``recency_half_life_days``.
- ``_apply_recency_weight`` math: half-life, weight=0 no-op, future-dated
  clamp.
- Backward compatibility: ``recency_weight=0.0`` produces identical
  output to the pre-0.6.7 call.
- End-to-end ranking: two patterns with identical similarity but
  different timestamps; the newer one ranks first under
  ``recency_weight > 0``.
- Composition with ``eval_weighted``.
"""

import math
import time

import pytest

from engramia.core.services.recall import _apply_recency_weight
from engramia.exceptions import ValidationError
from engramia.types import Match, Pattern


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAY = 86400.0


def _make_match(
    *,
    key: str,
    task: str,
    timestamp: float,
    similarity: float = 0.9,
    effective_score: float | None = None,
    success_score: float = 5.0,
) -> Match:
    """Build a Match with explicit timestamp for recency-math tests."""
    pattern = Pattern(
        task=task,
        design={"code": "pass"},
        success_score=success_score,
        timestamp=timestamp,
    )
    return Match(
        pattern=pattern,
        similarity=similarity,
        reuse_tier="adapt",
        pattern_key=key,
        effective_score=effective_score,
    )


def _save_pattern_with_timestamp(
    mem,
    storage,
    embeddings,
    key: str,
    task: str,
    timestamp: float,
    success_score: float = 5.0,
) -> None:
    """Persist a Pattern + its embedding + its eval record under ``key``.

    Goes around ``Memory.learn()`` so the caller can pin the stored
    ``timestamp`` (learn uses ``time.time()`` via the default factory
    and also runs dedup, which would collapse near-duplicate task text
    back to one pattern). ``eval_weighted=True`` reads from the
    ``eval_store`` (multiplier in [0.5, 1.0]) rather than from
    ``Pattern.success_score`` — so we also write an eval record to
    keep test expectations consistent with what a real learn() would
    produce.
    """
    pattern = Pattern(
        task=task,
        design={"code": "pass"},
        success_score=success_score,
        timestamp=timestamp,
    )
    storage.save(key, pattern.model_dump())
    storage.save_embedding(key, embeddings.embed(task))
    mem._eval_store.save(
        agent_name=key,
        task=task,
        scores={"overall": success_score, "feedback": ""},
    )


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


class TestRecencyValidators:
    def test_weight_below_zero_rejected(self, mem):
        with pytest.raises(ValidationError, match="recency_weight"):
            mem.recall(task="any", recency_weight=-0.01)

    def test_weight_above_one_rejected(self, mem):
        with pytest.raises(ValidationError, match="recency_weight"):
            mem.recall(task="any", recency_weight=1.01)

    def test_half_life_zero_rejected(self, mem):
        with pytest.raises(ValidationError, match="recency_half_life_days"):
            mem.recall(task="any", recency_weight=1.0, recency_half_life_days=0.0)

    def test_half_life_negative_rejected(self, mem):
        with pytest.raises(ValidationError, match="recency_half_life_days"):
            mem.recall(task="any", recency_weight=1.0, recency_half_life_days=-5.0)

    def test_weight_zero_accepts_any_half_life(self, mem):
        # weight=0 is a no-op but the half-life is still validated as > 0.
        # Keeping the validator active avoids action-at-a-distance: a caller
        # who later bumps weight without revisiting half_life would get a
        # silent divide-by-zero instead of a loud error.
        with pytest.raises(ValidationError, match="recency_half_life_days"):
            mem.recall(task="any", recency_weight=0.0, recency_half_life_days=-1.0)


# ---------------------------------------------------------------------------
# _apply_recency_weight math
# ---------------------------------------------------------------------------


class TestRecencyMath:
    def test_weight_zero_is_noop(self):
        now = 1_000_000_000.0
        matches = [
            _make_match(key="a", task="a", timestamp=now - 100 * _DAY, similarity=0.5),
            _make_match(key="b", task="b", timestamp=now, similarity=0.6),
        ]
        out = _apply_recency_weight(matches, weight=0.0, half_life_days=30.0, now=now)
        # Same list, same scores, no mutation.
        assert out is matches
        assert out[0].effective_score is None
        assert out[1].effective_score is None

    def test_half_life_factor_is_half(self):
        now = 1_000_000_000.0
        m = _make_match(
            key="k", task="x", timestamp=now - 30 * _DAY, similarity=1.0, effective_score=None
        )
        out = _apply_recency_weight([m], weight=1.0, half_life_days=30.0, now=now)
        assert math.isclose(out[0].effective_score, 0.5, abs_tol=1e-6)

    def test_fresh_pattern_factor_is_one(self):
        now = 1_000_000_000.0
        m = _make_match(key="k", task="x", timestamp=now, similarity=0.8, effective_score=None)
        out = _apply_recency_weight([m], weight=1.0, half_life_days=30.0, now=now)
        assert math.isclose(out[0].effective_score, 0.8, abs_tol=1e-6)

    def test_future_timestamp_clamped(self):
        now = 1_000_000_000.0
        # Pattern stored "in the future" (clock skew): age is clamped to 0,
        # recency_factor is 1.0, so the score equals the base — NOT > base.
        m = _make_match(
            key="k", task="x", timestamp=now + 5 * _DAY, similarity=0.7, effective_score=None
        )
        out = _apply_recency_weight([m], weight=1.0, half_life_days=30.0, now=now)
        assert math.isclose(out[0].effective_score, 0.7, abs_tol=1e-6)

    def test_two_half_lives_is_quarter(self):
        now = 1_000_000_000.0
        m = _make_match(key="k", task="x", timestamp=now - 60 * _DAY, similarity=1.0)
        out = _apply_recency_weight([m], weight=1.0, half_life_days=30.0, now=now)
        assert math.isclose(out[0].effective_score, 0.25, abs_tol=1e-6)

    def test_weight_half_softens_decay(self):
        now = 1_000_000_000.0
        m = _make_match(key="k", task="x", timestamp=now - 30 * _DAY, similarity=1.0)
        # factor = 0.5; 0.5 ** 0.5 ≈ 0.7071
        out = _apply_recency_weight([m], weight=0.5, half_life_days=30.0, now=now)
        assert math.isclose(out[0].effective_score, 0.5**0.5, abs_tol=1e-6)

    def test_re_sorts_by_effective(self):
        now = 1_000_000_000.0
        matches = [
            _make_match(key="old", task="a", timestamp=now - 300 * _DAY, similarity=0.9),
            _make_match(key="new", task="b", timestamp=now, similarity=0.6),
        ]
        # Old has higher similarity but much older; at weight=1 + half_life=30
        # the new one should win.
        out = _apply_recency_weight(matches, weight=1.0, half_life_days=30.0, now=now)
        assert out[0].pattern_key == "new"
        assert out[1].pattern_key == "old"

    def test_composes_with_existing_effective_score(self):
        now = 1_000_000_000.0
        m = _make_match(
            key="k",
            task="x",
            timestamp=now - 30 * _DAY,
            similarity=1.0,
            effective_score=0.8,  # already eval-weighted
        )
        out = _apply_recency_weight([m], weight=1.0, half_life_days=30.0, now=now)
        # 0.8 * 0.5 ** 1 = 0.4
        assert math.isclose(out[0].effective_score, 0.4, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# End-to-end through Memory.recall()
# ---------------------------------------------------------------------------


class TestRecencyRecallBackwardCompat:
    def test_default_kwargs_match_explicit_zero(self, mem):
        mem.learn(task="Write a CSV parser in Python", code="pass", eval_score=7.0)
        mem.learn(task="Render a scatter plot with matplotlib", code="pass", eval_score=7.0)

        baseline = mem.recall(task="Parse CSV data", limit=5, readonly=True)
        zero_weight = mem.recall(
            task="Parse CSV data",
            limit=5,
            recency_weight=0.0,
            readonly=True,
        )
        assert len(baseline) == len(zero_weight)
        for b, w in zip(baseline, zero_weight):
            assert b.pattern_key == w.pattern_key
            assert b.similarity == w.similarity
            assert b.effective_score == w.effective_score


class TestRecencyRecallRanking:
    def test_newer_wins_when_similarity_is_equal(self, mem, storage, fake_embeddings):
        now = time.time()
        task_text = "Same task text repeated twice for recency ranking"
        _save_pattern_with_timestamp(
            mem, storage, fake_embeddings, "patterns/old", task_text, now - 60 * _DAY, success_score=7.0
        )
        _save_pattern_with_timestamp(
            mem, storage, fake_embeddings, "patterns/new", task_text, now, success_score=7.0
        )

        # Without recency, both patterns share the same embedding (FakeEmbeddings
        # is deterministic on task text) so ranking between them is arbitrary —
        # we just check the top-1 is one of the two.
        plain = mem.recall(task=task_text, limit=2, deduplicate=False, readonly=True)
        assert {m.pattern_key for m in plain} == {"patterns/old", "patterns/new"}

        # With full recency, the newer one must rank first.
        weighted = mem.recall(
            task=task_text,
            limit=2,
            deduplicate=False,
            recency_weight=1.0,
            recency_half_life_days=30.0,
            readonly=True,
        )
        assert weighted[0].pattern_key == "patterns/new"
        assert weighted[1].pattern_key == "patterns/old"
        # And the effective_score of the newer one is meaningfully higher.
        assert weighted[0].effective_score > weighted[1].effective_score

    def test_plain_path_populates_effective_score_when_recency_active(
        self, mem, storage, fake_embeddings
    ):
        # eval_weighted=False would have left effective_score=None before
        # 0.6.7; with recency_weight>0 it must be populated so the caller
        # can see the blended ranking signal.
        now = time.time()
        task_text = "Task text for plain path effective_score check"
        _save_pattern_with_timestamp(
            mem, storage, fake_embeddings, "patterns/only", task_text, now - 10 * _DAY, success_score=7.0
        )
        matches = mem.recall(
            task=task_text,
            limit=1,
            eval_weighted=False,
            recency_weight=1.0,
            recency_half_life_days=30.0,
            readonly=True,
        )
        assert len(matches) == 1
        assert matches[0].effective_score is not None
        assert 0.0 < matches[0].effective_score < 1.0


class TestRecencyComposesWithEvalWeighted:
    def test_older_but_higher_quality_can_win_at_low_weight(
        self, mem, storage, fake_embeddings
    ):
        # Two patterns with the same task text so similarity is identical
        # (FakeEmbeddings is deterministic):
        #   "old" — 180 days old, success_score 9.5 (high quality)
        #   "new" — just stored, success_score 5.0 (low quality)
        # At recency_weight=0.0 + eval_weighted=True the high-quality old
        # one should win. At recency_weight=1.0 + eval_weighted=True the
        # recent one should win.
        now = time.time()
        task_text = "Task text identical across quality tiers"
        _save_pattern_with_timestamp(
            mem,
            storage,
            fake_embeddings,
            "patterns/old_high_q",
            task_text,
            now - 180 * _DAY,
            success_score=9.5,
        )
        _save_pattern_with_timestamp(
            mem,
            storage,
            fake_embeddings,
            "patterns/new_low_q",
            task_text,
            now,
            success_score=5.0,
        )

        quality_only = mem.recall(
            task=task_text,
            limit=2,
            deduplicate=False,
            eval_weighted=True,
            recency_weight=0.0,
            readonly=True,
        )
        assert quality_only[0].pattern_key == "patterns/old_high_q"

        recency_heavy = mem.recall(
            task=task_text,
            limit=2,
            deduplicate=False,
            eval_weighted=True,
            recency_weight=1.0,
            recency_half_life_days=30.0,
            readonly=True,
        )
        assert recency_heavy[0].pattern_key == "patterns/new_low_q"
