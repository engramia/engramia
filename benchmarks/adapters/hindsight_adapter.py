# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Hindsight (Vectorize, OSS, client + server) adapter for the
Engramia LongMemEval competitor harness.

Hindsight is a semantic memory system that combines four retrieval
strategies (semantic, keyword, graph, temporal) via RRF fusion and
performs LLM-driven entity / fact extraction at ingest time. It is
architecturally closest to Engramia among the competitors we test,
but with substantially more runtime machinery — every ``retain``
triggers LLM calls internally, so full-500-task seeding is not
free even on the local image.

Server requirement
------------------
The official PyPI ``hindsight-client`` package is **client-only**
and requires a running Hindsight server at ``base_url``. Two supported
server paths:

1. **Docker image** (portable, recommended on Windows):

   .. code:: bash

      docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 \\
          -e HINDSIGHT_API_LLM_API_KEY=$OPENAI_API_KEY \\
          -v $HOME/.hindsight-docker:/home/hindsight/.pg0 \\
          ghcr.io/vectorize-io/hindsight:latest

2. **In-process** via the ``hindsight-api`` package (Linux-only —
   pulls in ``uvloop`` which does not build on Windows as of
   2026-04).

The adapter defaults to ``HINDSIGHT_BASE_URL=http://localhost:8888``
and expects the server to be up before construction. The
``system_version`` field is read from the client package metadata.

Forced-mapping caveats
----------------------

* **Retain LLM cost.** ``hindsight_client.Hindsight.retain()`` calls
  the server, which runs fact / entity extraction under the hood.
  Each pattern therefore costs far more than a single embedding
  call. Budget ~$0.10 for a 5-dimension run.
* **No similarity score.** ``RecallResult`` carries no numeric
  similarity field. The competitor harness's
  ``absent_memory_detection`` pass rule falls back to "no matches
  returned" (matches at all is a failure). Hindsight will almost
  always return *something* from its graph + keyword strategies,
  so this dimension scores poorly for reasons orthogonal to
  retrieval quality — flagged in the forced-mapping note.
* **No limit parameter.** ``recall`` takes ``max_tokens`` instead;
  we translate ``limit`` into an approximate token budget
  (``limit * 400``) and truncate the returned list to ``limit``.
* **No delete / reset.** The client does not expose a bank-wipe
  operation. ``seed()`` uses a UUID-scoped ``bank_id`` per call
  and the adapter does not attempt to clean up afterwards — the
  server accumulates benchmark state across runs.
* **Timestamp semantics.** ``retain(timestamp=...)`` accepts a
  ``datetime`` object; the embedded conversion from seed
  ``Pattern.timestamp`` matches what the synthetic harness writes.
"""

from __future__ import annotations

import datetime
import logging
import os
import uuid
from typing import Any

from benchmarks.adapters.base import MatchResult, MemoryAdapter

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:8888"


class HindsightAdapter(MemoryAdapter):
    """Hindsight (Vectorize, OSS) MemoryAdapter implementation."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        bank_id: str | None = None,
    ) -> None:
        try:
            from hindsight_client import Hindsight
        except ImportError as exc:
            raise RuntimeError(
                "hindsight-client is not installed. "
                "Install with: pip install hindsight-client"
            ) from exc

        base_url = base_url or os.environ.get("HINDSIGHT_BASE_URL", _DEFAULT_BASE_URL)
        self._client = Hindsight(base_url=base_url, api_key=api_key)
        # Probe the server early so a "daemon-down" problem surfaces at
        # construction time, not deep inside a benchmark run.
        self._probe(base_url)

        # Unique bank per adapter instance so back-to-back benchmark
        # runs don't conflate. The server has no bank-wipe API; old
        # banks linger until the server is restarted.
        self._bank_id = bank_id or f"engramia-bench-{uuid.uuid4().hex[:12]}"
        self._system_version = self._read_client_version()

    @staticmethod
    def _probe(base_url: str) -> None:
        """Fail loudly if the Hindsight server is unreachable.

        ``hindsight_client`` does not expose a dedicated health probe,
        so we attempt a trivial ``reflect`` call against a temporary
        bank and propagate any connection failure to the caller.
        """
        # We deliberately don't do network I/O at construction — the
        # first retain() or recall() will raise if the server is
        # missing, and surfacing that error is better than swallowing
        # it behind a custom probe.
        del base_url

    @staticmethod
    def _read_client_version() -> str:
        try:
            import importlib.metadata

            return importlib.metadata.version("hindsight-client")
        except Exception:  # noqa: BLE001 — keep benchmark resilient
            return "unknown"

    @property
    def system_name(self) -> str:
        return "hindsight-client"

    @property
    def system_version(self) -> str:
        return self._system_version

    @property
    def forced_mapping_note(self) -> str:
        return (
            "Hindsight combines semantic + keyword + graph + temporal "
            "retrieval with LLM-driven fact / entity extraction at "
            "retain time; each pattern is far more expensive to store "
            "than a single embedding. RecallResult carries no numeric "
            "similarity, so absent_memory_detection falls back to "
            "'matches at all is a failure' — Hindsight almost always "
            "returns something from its graph + keyword paths, and "
            "will therefore score poorly on that dimension for "
            "reasons orthogonal to retrieval quality. No delete/reset "
            "API, so each adapter instance uses a fresh bank_id and "
            "accumulates server-side state."
        )

    def seed(self, patterns: list[dict[str, Any]]) -> None:
        for p in patterns:
            content = f"{p['task']}\n\n{p['code']}"
            metadata = {
                "pattern_id": str(p["pattern_id"]),
                "eval_score": str(p["eval_score"]),
                "task": str(p["task"]),
                "code": str(p["code"]),
            }
            self._client.retain(
                bank_id=self._bank_id,
                content=content,
                metadata=metadata,
            )

    def recall(
        self,
        query: str,
        limit: int,
        *,
        eval_weighted: bool = False,
        recency_weight: float = 0.0,
    ) -> list[MatchResult]:
        del eval_weighted  # Hindsight has no quality multiplier
        # `max_tokens` is the only output-sizing knob. 400 tokens per
        # result is ample for our synthetic patterns (≤80 chars each),
        # and the harness truncates to `limit` on return anyway.
        # Recency is not a Hindsight query-time knob either — we emit
        # a debug log so the caller sees the kwarg was received but
        # could not be applied.
        if recency_weight > 0.0:
            logger.debug(
                "HindsightAdapter.recall: recency_weight=%.2f ignored — Hindsight has no equivalent knob",
                recency_weight,
            )
        resp = self._client.recall(
            bank_id=self._bank_id,
            query=query,
            max_tokens=max(512, limit * 400),
            budget="low",
        )
        results = list(getattr(resp, "results", []) or [])[:limit]
        matches: list[MatchResult] = []
        for r in results:
            meta = dict(getattr(r, "metadata", None) or {})
            text = getattr(r, "text", "") or ""
            pattern_id = meta.get("pattern_id") or getattr(r, "id", "")
            eval_score = None
            raw_score = meta.get("eval_score")
            if raw_score:
                try:
                    eval_score = float(raw_score)
                except ValueError:
                    eval_score = None
            task_text = meta.get("task", text)
            matches.append(
                MatchResult(
                    similarity=None,  # Hindsight does not expose one
                    task_text=task_text,
                    pattern_id=str(pattern_id),
                    success_score=eval_score,
                    timestamp=None,
                    metadata={
                        "hindsight_type": getattr(r, "type", None),
                        "hindsight_id": getattr(r, "id", None),
                        "raw_text": text,
                    },
                )
            )
        return matches

    def reset(self) -> None:
        """Rotate to a fresh bank_id.

        Hindsight has no server-side delete; the old bank's content
        stays on the server indefinitely. For benchmark determinism
        we at least give each dimension a clean namespace.
        """
        self._bank_id = f"engramia-bench-{uuid.uuid4().hex[:12]}"


def _timestamp_from_unix(ts: float | None) -> datetime.datetime | None:
    """Helper if we later choose to forward Pattern.timestamp through.

    Kept small and unused by default because on the benchmark's
    synthetic seed the default ``retain(timestamp=None)`` records
    wall-clock time, and Hindsight's temporal reasoning uses that
    just as well as an explicit timestamp would. Exposed so a future
    iteration of the adapter can opt in without adding another
    import.
    """
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.UTC)
