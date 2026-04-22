# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""LongMemEval (Wu et al. 2024) — real-dataset port against Engramia.

Runs the official LongMemEval benchmark's **Oracle** variant against
Engramia's ``Memory.recall``. Oracle supplies only the evidence
sessions per question (no noise haystack), which matches Engramia's
current scope — semantic recall quality on a curated pattern pool,
not scale-out haystack retrieval. Scale-out (the ``_s`` and ``_m``
variants) is deferred until Engramia has a sharded storage backend
worth benchmarking.

Protocol
--------
For each question in the filtered subset:

1. Spawn a fresh ``Memory`` instance.
2. Ingest every ``haystack_session`` as one ``mem.learn()`` call
   (``task`` = concatenated turns, ``design.session_id`` = the
   session id, ``Pattern.timestamp`` overwritten to the session's
   ``haystack_date``).
3. Call ``mem.recall(question, limit=5, recency_weight=1.0)`` —
   recency bias matches the "temporal" flavor of most questions
   and is a no-op on questions where it doesn't help.
4. Two metrics captured per question:

   * **retrieval_hit** — objective, cheap. Did the recalled top-K
     include any of ``answer_session_ids``?
   * **qa_correct** — subjective, LLM-judge. Synthesize a hypothesis
     with ``gpt-4o-mini`` given the recalled context, then judge
     it against the ground-truth ``answer`` (also ``gpt-4o-mini``).

5. Cost tallied per call and emitted in the result JSON.

Differences from the paper (flagged in every emitted JSON):

* Judge model is ``gpt-4o-mini`` by default (paper uses
  ``gpt-4o``). Override with ``--judge-model``.
* Scale variant is Oracle (paper's S/M variants hold the full
  haystack). Engramia's scale-out story is tracked separately.

Usage
-----
.. code:: bash

    python -m benchmarks.longmemeval_real \\
        --category temporal-reasoning \\
        --output benchmarks/results/longmemeval_real_temporal_2026-04-22.json

    # All categories (~500 questions, ~$0.45 on gpt-4o-mini):
    python -m benchmarks.longmemeval_real --output results/longmemeval_real_all.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "data" / "longmemeval_oracle.json"
DEFAULT_OUTPUT = Path(__file__).parent / "results" / "longmemeval_real_oracle.json"

VALID_CATEGORIES = {
    "temporal-reasoning",
    "multi-session",
    "knowledge-update",
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
}

# Per-million-token pricing (USD) as of 2026-04. Keep this narrow so that
# the emitted cost estimate in result JSON is self-documenting; don't
# chase provider price updates in the middle of a benchmark run.
_PRICING = {
    "text-embedding-3-small": {"in": 0.020, "out": 0.0},
    "gpt-4o-mini": {"in": 0.150, "out": 0.600},
    "gpt-4o": {"in": 2.500, "out": 10.000},
}

# Synthesis + judge tuning — keeps the recall context well under
# gpt-4o-mini's efficient input budget while preserving enough of the
# top match text for the LLM to synthesize a grounded answer.
_SYNTH_CONTEXT_TOP_K = 3
_SYNTH_SESSION_CHAR_CAP = 2000
_SYNTH_MAX_OUT_TOKENS = 200
_JUDGE_MAX_OUT_TOKENS = 80


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class QuestionResult:
    question_id: str
    category: str
    retrieval_hit: bool
    qa_correct: bool | None
    recalled_session_ids: list[str]
    hypothesis: str | None
    reason: str | None


@dataclass
class CostTally:
    embedding_in_tokens: int = 0
    synth_in_tokens: int = 0
    synth_out_tokens: int = 0
    judge_in_tokens: int = 0
    judge_out_tokens: int = 0

    def add_embedding(self, tokens: int) -> None:
        self.embedding_in_tokens += tokens

    def add_synth(self, in_t: int, out_t: int) -> None:
        self.synth_in_tokens += in_t
        self.synth_out_tokens += out_t

    def add_judge(self, in_t: int, out_t: int) -> None:
        self.judge_in_tokens += in_t
        self.judge_out_tokens += out_t

    def estimate_usd(self, embed_model: str, chat_model: str) -> dict[str, float]:
        e = _PRICING.get(embed_model, {"in": 0.0, "out": 0.0})
        c = _PRICING.get(chat_model, {"in": 0.0, "out": 0.0})
        embed_usd = self.embedding_in_tokens * e["in"] / 1_000_000
        synth_usd = (self.synth_in_tokens * c["in"] + self.synth_out_tokens * c["out"]) / 1_000_000
        judge_usd = (self.judge_in_tokens * c["in"] + self.judge_out_tokens * c["out"]) / 1_000_000
        return {
            "embedding_usd": round(embed_usd, 6),
            "synthesis_usd": round(synth_usd, 6),
            "judge_usd": round(judge_usd, 6),
            "total_usd": round(embed_usd + synth_usd + judge_usd, 6),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_session_date_to_epoch(date_str: str) -> float:
    """Convert LongMemEval date string to Unix seconds.

    Dataset format is ``"YYYY/MM/DD (DayName) HH:MM"``.
    """
    stripped = date_str.split("(")[0].strip() + " " + date_str.split(")")[1].strip()
    dt = datetime.datetime.strptime(stripped, "%Y/%m/%d %H:%M")
    return dt.replace(tzinfo=datetime.UTC).timestamp()


def _concat_session_text(session: list[dict[str, Any]]) -> str:
    """Flatten one session's user / assistant turns into one string."""
    lines = []
    for turn in session:
        role = turn.get("role", "?")
        content = turn.get("content", "")
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _pair_turns(session: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Collapse a session's ordered turns into (user, assistant) pairs.

    Sessions in LongMemEval alternate user / assistant but aren't
    guaranteed to: if we find two user turns in a row we emit the
    first with an empty assistant response rather than dropping
    content. A trailing user turn also gets an empty response.
    """
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(session):
        turn = session[i]
        role = turn.get("role")
        content = turn.get("content", "") or ""
        if role == "user":
            assistant_content = ""
            if i + 1 < len(session) and session[i + 1].get("role") == "assistant":
                assistant_content = session[i + 1].get("content", "") or ""
                i += 2
            else:
                i += 1
            pairs.append((content, assistant_content))
        elif role == "assistant":
            # Assistant turn with no preceding user turn — emit as a
            # pair with a blank user side so nothing is dropped.
            pairs.append(("", content))
            i += 1
        else:
            i += 1
    return pairs


def _truncate_to_chars(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + "  …[truncated]"


# ---------------------------------------------------------------------------
# Judge + synthesis prompts
# ---------------------------------------------------------------------------

_SYNTH_SYSTEM = (
    "You are a retrieval-augmented question answering system. Given a "
    "question and a bundle of chat-session excerpts from the user's "
    "history, produce the shortest grounded answer. If the context does "
    "not contain the answer, say \"NOT_IN_CONTEXT\". No preamble."
)

_JUDGE_SYSTEM = (
    "You are a strict evaluator. Given a question, a reference answer, "
    "and a hypothesis, decide whether the hypothesis conveys the same "
    "factual content as the reference. Reply with JSON "
    "{\"verdict\": \"correct\"|\"incorrect\", \"reason\": \"...\"}. "
    "A hypothesis that adds plausible-sounding but unverifiable detail "
    "beyond the reference is still correct if the reference content is "
    "present and not contradicted. Exact wording is not required."
)


def _build_synth_prompt(question: str, question_date: str, context: str) -> str:
    return (
        f"Question (asked on {question_date}):\n{question}\n\n"
        f"Context (top recalled sessions, most-recent-first):\n{context}\n\n"
        "Answer:"
    )


def _build_judge_prompt(question: str, reference: str, hypothesis: str) -> str:
    return (
        f"Question: {question}\n"
        f"Reference answer: {reference}\n"
        f"Hypothesis: {hypothesis}\n"
        "Decide."
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class LongMemEvalRealRunner:
    """Run the Oracle variant of LongMemEval against Engramia."""

    def __init__(
        self,
        dataset_path: Path = DATASET_PATH,
        judge_model: str = "gpt-4o-mini",
        synth_model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
        max_questions: int | None = None,
        offset: int = 0,
    ) -> None:
        self.dataset_path = dataset_path
        self.judge_model = judge_model
        self.synth_model = synth_model
        self.embedding_model = embedding_model
        self.max_questions = max_questions
        self.offset = offset

    # ------------------------------------------------------------------
    # Dataset
    # ------------------------------------------------------------------

    def _load_dataset(self, category: str | None) -> list[dict[str, Any]]:
        with self.dataset_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if category:
            data = [d for d in data if d.get("question_type") == category]
        if self.offset:
            data = data[self.offset :]
        if self.max_questions is not None:
            data = data[: self.max_questions]
        return data

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def _seed_memory(self, mem: Any, question: dict[str, Any], tally: CostTally) -> None:
        """Ingest haystack sessions as one pattern per user/assistant turn pair.

        ``Memory.learn()`` caps ``task`` at 10 k chars, which is well
        below the length of a typical Oracle session (~15 k). Splitting
        at the natural (user, assistant) turn-pair boundary fits the
        cap comfortably (max observed turn ≈ 4.3 k chars) and matches
        Engramia's execution-memory mental model — one task + response
        per pattern, not one whole conversation per pattern.

        ``Pattern.timestamp`` is overwritten to the session's
        ``haystack_date`` by post-save mutation so
        ``recall(recency_weight=...)`` sees the real temporal
        distribution, not the wall-clock gaps between ``mem.learn``
        calls. Every pattern belonging to the same session shares the
        session's date, so recency ordering between sessions is honest
        without imposing artificial per-turn timestamps.

        The newly-created ``pattern_key`` is identified per-``learn``
        call by diffing ``storage.list_keys`` snapshots (``LearnResult``
        does not expose the key directly). ``on_duplicate='keep_both'``
        so Jaccard-similar turns from different sessions cannot collide
        under dedup and drop one session's data — each session must be
        independently recallable for the retrieval-hit metric to mean
        anything.
        """
        sessions = question["haystack_sessions"]
        session_ids = question["haystack_session_ids"]
        session_dates = question["haystack_dates"]
        storage = mem._storage  # noqa: SLF001 — benchmark harness is allowed
        before_keys = set(storage.list_keys(prefix="patterns/"))
        for sess, sid, date_str in zip(sessions, session_ids, session_dates, strict=True):
            try:
                ts = _parse_session_date_to_epoch(date_str)
            except ValueError:
                logger.warning("Could not parse date %r for session %s", date_str, sid)
                ts = None
            for user_text, assistant_text in _pair_turns(sess):
                task_text = _truncate_to_chars(user_text, 9_500)
                code_text = _truncate_to_chars(assistant_text, 9_500)
                if not task_text.strip():
                    # ``mem.learn`` rejects empty / whitespace-only tasks.
                    # An assistant-first turn without any user content
                    # cannot be indexed as a pattern; skip it.
                    continue
                if not code_text.strip():
                    code_text = "[no assistant response captured]"
                tally.add_embedding(len(task_text) // 4)
                mem.learn(
                    task=task_text,
                    code=code_text,
                    eval_score=5.0,
                    classification="public",
                    source="benchmark",
                    on_duplicate="keep_both",
                )
                # Identify the just-created key by set diff, then rewrite
                # timestamp + session metadata directly on storage.
                after_keys = set(storage.list_keys(prefix="patterns/"))
                new_keys = after_keys - before_keys
                before_keys = after_keys
                for new_key in new_keys:
                    data = storage.load(new_key)
                    if not data:
                        continue
                    if ts is not None:
                        data["timestamp"] = ts
                    design = data.get("design") or {}
                    design["session_id"] = sid
                    design["session_date"] = date_str
                    data["design"] = design
                    storage.save(new_key, data)

    # ------------------------------------------------------------------
    # Per-question evaluation
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        question: dict[str, Any],
        llm: Any,
        embeddings: Any,
        tally: CostTally,
    ) -> QuestionResult:
        from engramia import Memory
        from engramia.providers import JSONStorage

        qid = question["question_id"]
        qtext = question["question"]
        qdate = question.get("question_date", "")
        answer_ref = question["answer"]
        answer_sids = set(question.get("answer_session_ids", []))

        with tempfile.TemporaryDirectory(prefix="engramia_lme_real_") as tmp:
            mem = Memory(embeddings=embeddings, storage=JSONStorage(path=Path(tmp)))
            self._seed_memory(mem, question, tally)

            # Query embedding cost is accounted for on the recall path
            # via Memory internals. Add the rough query token count.
            tally.add_embedding(len(qtext) // 4)
            # recency_weight=0.0 (default) is the honest baseline: a caller
            # asking a temporal question may want the newest OR the oldest
            # session ("what happened first?"), so biasing ranking toward
            # "recent" sabotages the latter class of questions. The knob
            # exists for workloads where the caller has domain knowledge
            # about the direction; the benchmark measures the default.
            matches = mem.recall(
                task=qtext,
                limit=5,
                deduplicate=False,
                eval_weighted=False,
                readonly=True,
            )
            recalled_session_ids = [m.pattern.design.get("session_id", "") for m in matches]
            retrieval_hit = bool(set(recalled_session_ids) & answer_sids)

        # Synthesis on the top-K recalled sessions.
        if not matches:
            return QuestionResult(
                question_id=qid,
                category=question["question_type"],
                retrieval_hit=False,
                qa_correct=False,
                recalled_session_ids=[],
                hypothesis=None,
                reason="no matches returned",
            )

        top = matches[:_SYNTH_CONTEXT_TOP_K]
        # Each pattern is one (user, assistant) turn pair. Feed both
        # sides to the synthesizer — the assistant response often
        # carries the factual content the user's turn only gestures at.
        context_blocks: list[str] = []
        for m in top:
            sid = m.pattern.design.get("session_id", "?")
            date = m.pattern.design.get("session_date", "")
            user_text = m.pattern.task
            assistant_text = m.pattern.design.get("code", "")
            block = (
                f"Session {sid} ({date})\n"
                f"[user] {_truncate_to_chars(user_text, _SYNTH_SESSION_CHAR_CAP // 2)}\n"
                f"[assistant] {_truncate_to_chars(assistant_text, _SYNTH_SESSION_CHAR_CAP // 2)}"
            )
            context_blocks.append(block)
        context = "\n\n---\n\n".join(context_blocks)
        synth_prompt = _build_synth_prompt(qtext, qdate, context)
        hypothesis, s_in, s_out = _chat_with_cost(
            llm,
            model=self.synth_model,
            system=_SYNTH_SYSTEM,
            user=synth_prompt,
            max_tokens=_SYNTH_MAX_OUT_TOKENS,
        )
        tally.add_synth(s_in, s_out)

        # Judge
        judge_prompt = _build_judge_prompt(qtext, answer_ref, hypothesis)
        verdict_raw, j_in, j_out = _chat_with_cost(
            llm,
            model=self.judge_model,
            system=_JUDGE_SYSTEM,
            user=judge_prompt,
            max_tokens=_JUDGE_MAX_OUT_TOKENS,
        )
        tally.add_judge(j_in, j_out)

        verdict, reason = _parse_judge_verdict(verdict_raw)

        return QuestionResult(
            question_id=qid,
            category=question["question_type"],
            retrieval_hit=retrieval_hit,
            qa_correct=verdict,
            recalled_session_ids=recalled_session_ids,
            hypothesis=hypothesis,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, category: str | None) -> dict[str, Any]:
        from engramia.providers.openai import OpenAIEmbeddings

        # We don't need the full Engramia LLM abstraction for judge /
        # synth calls — go straight to the OpenAI client so we can
        # capture token usage per call.
        from openai import OpenAI

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. This benchmark requires an "
                "OpenAI key for both embeddings and the LLM judge. "
                "Set it in the shell or in Core/.env before invoking."
            )
        llm = OpenAI()
        embeddings = OpenAIEmbeddings()

        questions = self._load_dataset(category)
        logger.info("Running %d questions (category=%s)", len(questions), category or "all")

        tally = CostTally()
        results: list[QuestionResult] = []
        t0 = time.monotonic()
        for i, q in enumerate(questions, 1):
            try:
                r = self._evaluate(q, llm, embeddings, tally)
            except Exception as exc:  # noqa: BLE001 — log + continue
                logger.exception("question %s failed: %s", q.get("question_id"), exc)
                r = QuestionResult(
                    question_id=q["question_id"],
                    category=q["question_type"],
                    retrieval_hit=False,
                    qa_correct=None,
                    recalled_session_ids=[],
                    hypothesis=None,
                    reason=f"exception: {type(exc).__name__}: {exc}",
                )
            results.append(r)
            if i % 10 == 0:
                logger.info("  progress %d / %d", i, len(questions))
        duration = time.monotonic() - t0

        try:
            from engramia import __version__ as engramia_version
        except ImportError:
            engramia_version = "unknown"

        return self._assemble_report(
            category=category,
            results=results,
            tally=tally,
            duration=duration,
            engramia_version=engramia_version,
        )

    def _assemble_report(
        self,
        *,
        category: str | None,
        results: list[QuestionResult],
        tally: CostTally,
        duration: float,
        engramia_version: str,
    ) -> dict[str, Any]:
        by_cat: dict[str, list[QuestionResult]] = {}
        for r in results:
            by_cat.setdefault(r.category, []).append(r)

        per_category = {}
        for cat, rs in by_cat.items():
            n = len(rs)
            retrieval_hits = sum(1 for r in rs if r.retrieval_hit)
            qa_correct = sum(1 for r in rs if r.qa_correct is True)
            qa_scored = sum(1 for r in rs if r.qa_correct is not None)
            per_category[cat] = {
                "total": n,
                "retrieval_hit": retrieval_hits,
                "retrieval_hit_rate": round(retrieval_hits / n, 4) if n else 0.0,
                "qa_correct": qa_correct,
                "qa_scored": qa_scored,
                "qa_correct_rate": round(qa_correct / qa_scored, 4) if qa_scored else 0.0,
            }

        cost = tally.estimate_usd(self.embedding_model, self.synth_model)

        return {
            "metadata": {
                "benchmark": "LongMemEval (Wu 2024) — Oracle variant",
                "dataset_version": "longmemeval-cleaned / longmemeval_oracle.json",
                "engramia_version": engramia_version,
                "embedding_model": self.embedding_model,
                "synth_model": self.synth_model,
                "judge_model": self.judge_model,
                "category_filter": category,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
                "duration_seconds": round(duration, 2),
                "reference_protocol_note": (
                    "Paper uses gpt-4o as judge; this run uses "
                    f"{self.judge_model}. Judge verdict drift vs paper "
                    "is expected but small on factual Q&A. Scale variant "
                    "is Oracle (only evidence sessions supplied) — not "
                    "testing haystack scale-out retrieval."
                ),
            },
            "results": {
                "total_questions": len(results),
                "per_category": per_category,
                "overall_retrieval_hit_rate": round(
                    sum(1 for r in results if r.retrieval_hit) / len(results), 4
                )
                if results
                else 0.0,
                "overall_qa_correct_rate": round(
                    sum(1 for r in results if r.qa_correct is True)
                    / max(1, sum(1 for r in results if r.qa_correct is not None)),
                    4,
                )
                if results
                else 0.0,
            },
            "cost_estimate_usd": cost,
            "raw_token_counts": {
                "embedding_in": tally.embedding_in_tokens,
                "synth_in": tally.synth_in_tokens,
                "synth_out": tally.synth_out_tokens,
                "judge_in": tally.judge_in_tokens,
                "judge_out": tally.judge_out_tokens,
            },
            "per_question": [
                {
                    "question_id": r.question_id,
                    "category": r.category,
                    "retrieval_hit": r.retrieval_hit,
                    "qa_correct": r.qa_correct,
                    "recalled_session_ids": r.recalled_session_ids,
                    "hypothesis": r.hypothesis,
                    "judge_reason": r.reason,
                }
                for r in results
            ],
        }


# ---------------------------------------------------------------------------
# Chat helpers (direct OpenAI client so we can read `.usage` back)
# ---------------------------------------------------------------------------


def _chat_with_cost(client: Any, *, model: str, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    """Run a single chat completion and return (text, in_tokens, out_tokens)."""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    in_tokens = usage.prompt_tokens if usage else 0
    out_tokens = usage.completion_tokens if usage else 0
    return text.strip(), in_tokens, out_tokens


def _parse_judge_verdict(raw: str) -> tuple[bool, str]:
    """Extract ``verdict`` + ``reason`` from the judge's JSON reply.

    Falls back to substring match on "correct"/"incorrect" if the reply
    isn't valid JSON (gpt-4o-mini is not perfectly reliable at JSON).
    """
    try:
        data = json.loads(raw)
        verdict = str(data.get("verdict", "")).strip().lower()
        reason = str(data.get("reason", "")).strip()
        return verdict == "correct", reason
    except (json.JSONDecodeError, TypeError):
        low = raw.lower()
        if "incorrect" in low:
            return False, raw[:200]
        if "correct" in low:
            return True, raw[:200]
        return False, f"unparseable: {raw[:200]}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="LongMemEval (Wu 2024) Oracle — run against Engramia",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--category",
        choices=sorted(VALID_CATEGORIES),
        default=None,
        help="Restrict to one category. Omit to run all 500.",
    )
    p.add_argument(
        "--max-questions",
        type=int,
        default=None,
        metavar="N",
        help="Cap at first N questions (useful for smoke tests).",
    )
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        metavar="N",
        help="Skip the first N questions (useful for batched runs).",
    )
    p.add_argument(
        "--judge-model",
        default="gpt-4o-mini",
        help="OpenAI model used by the LLM judge. Paper uses gpt-4o.",
    )
    p.add_argument(
        "--synth-model",
        default="gpt-4o-mini",
        help="OpenAI model used to synthesize the hypothesis.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="FILE",
        help="Write results JSON to FILE.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    runner = LongMemEvalRealRunner(
        judge_model=args.judge_model,
        synth_model=args.synth_model,
        max_questions=args.max_questions,
        offset=args.offset,
    )
    report = runner.run(category=args.category)

    _print_summary(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


def _print_summary(report: dict[str, Any]) -> None:
    meta = report["metadata"]
    res = report["results"]
    cost = report["cost_estimate_usd"]
    print()
    print("=" * 72)
    print("  LongMemEval (Wu 2024, Oracle) vs Engramia")
    print("=" * 72)
    print(f"  Engramia: {meta['engramia_version']}   Embedding: {meta['embedding_model']}")
    print(f"  Synth: {meta['synth_model']}   Judge: {meta['judge_model']}")
    print(f"  Category filter: {meta['category_filter'] or 'ALL'}   Duration: {meta['duration_seconds']}s")
    print()
    print(f"  {'Category':<30} {'Retrieval':>10}  {'Q&A':>10}  {'Count':>6}")
    print(f"  {'-' * 30} {'-' * 10}  {'-' * 10}  {'-' * 6}")
    for cat, stats in res["per_category"].items():
        r_rate = stats["retrieval_hit_rate"] * 100
        q_rate = stats["qa_correct_rate"] * 100
        print(f"  {cat:<30} {r_rate:>9.1f}%  {q_rate:>9.1f}%  {stats['total']:>6}")
    print()
    print(f"  {'OVERALL':<30} {res['overall_retrieval_hit_rate'] * 100:>9.1f}%  "
          f"{res['overall_qa_correct_rate'] * 100:>9.1f}%  {res['total_questions']:>6}")
    print()
    print(f"  Cost: ${cost['total_usd']:.4f} total "
          f"(embed ${cost['embedding_usd']:.4f} + "
          f"synth ${cost['synthesis_usd']:.4f} + "
          f"judge ${cost['judge_usd']:.4f})")
    print("=" * 72)
    print()


if __name__ == "__main__":
    raise SystemExit(main())
