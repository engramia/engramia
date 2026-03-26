"""Recurring eval feedback pattern store.

Tracks which quality issues appear repeatedly across evaluations so they
can be automatically injected into coder/architect prompts.

Patterns decay faster than success patterns (10% per week) so only current
issues stay surfaced. Patterns appearing fewer than 2 times are not surfaced.
"""

import datetime
import logging
import re
import time

from agent_brain._util import jaccard
from agent_brain.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_KEY = "feedback/_list"
_MAX_KEEP = 50
_MAX_FEEDBACK_LEN = 5000
_DECAY_PER_WEEK = 0.90  # 10% decay per week (faster than success patterns)
_MIN_SCORE = 0.15
_CLUSTER_THRESHOLD = 0.4  # Jaccard threshold for grouping similar feedback


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class EvalFeedbackStore:
    """Tracks recurring quality issues from evaluations.

    Args:
        storage: Storage backend to persist feedback patterns.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, feedback_text: str) -> None:
        """Record a feedback string from an evaluation.

        Similar feedbacks are clustered together (Jaccard > 0.4).
        Each cluster's count and score are incremented.

        Args:
            feedback_text: Raw feedback string from evaluator.

        Raises:
            ValueError: If feedback_text exceeds maximum length.
        """
        if len(feedback_text) > _MAX_FEEDBACK_LEN:
            raise ValueError(f"feedback_text exceeds maximum length of {_MAX_FEEDBACK_LEN} characters")
        norm = _normalize(feedback_text)
        if not norm:
            return

        patterns = self._load_raw()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

        for p in patterns:
            if jaccard(_normalize(p["pattern"]), norm) > _CLUSTER_THRESHOLD:
                p["count"] += 1
                p["score"] = min(p["score"] + 0.1, 1.0)
                p["last_seen"] = now_iso
                self._storage.save(_KEY, patterns)
                return

        patterns.append(
            {"pattern": feedback_text.strip(), "count": 1, "score": 0.5, "last_seen": now_iso, "last_decayed": now_iso}
        )
        patterns = patterns[-_MAX_KEEP:]
        self._storage.save(_KEY, patterns)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_top(self, n: int = 5, task_type: str | None = None) -> list[str]:
        """Return the most relevant recurring feedback strings.

        Only patterns with count >= 2 are returned (avoids one-offs).

        Args:
            n: Maximum number of feedback strings to return.
            task_type: Optional filter — only return patterns whose text
                contains the task_type string (case-insensitive).

        Returns:
            List of feedback strings sorted by relevance.
        """
        patterns = self._load_raw()
        recurring = [p for p in patterns if p["count"] >= 2]

        if task_type:
            recurring = [p for p in recurring if task_type.lower() in p["pattern"].lower()]

        recurring.sort(key=lambda p: p["score"] * p["count"], reverse=True)
        return [p["pattern"] for p in recurring[:n]]

    # ------------------------------------------------------------------
    # Decay
    # ------------------------------------------------------------------

    def run_decay(self) -> int:
        """Apply weekly decay to all patterns, prune those below MIN_SCORE.

        Returns:
            Number of patterns pruned.
        """
        patterns = self._load_raw()
        now = time.time()
        surviving = []

        for p in patterns:
            last_decayed_ts = _parse_iso(p.get("last_decayed", p.get("last_seen", "")))
            elapsed_weeks = (now - last_decayed_ts) / (7 * 24 * 3600) if last_decayed_ts else 0
            decayed = p["score"] * (_DECAY_PER_WEEK**elapsed_weeks)
            if decayed >= _MIN_SCORE:
                p["score"] = round(decayed, 4)
                p["last_decayed"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
                surviving.append(p)

        pruned = len(patterns) - len(surviving)
        self._storage.save(_KEY, surviving)
        return pruned

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_raw(self) -> list:
        data = self._storage.load(_KEY)
        return data if isinstance(data, list) else []


def _parse_iso(iso: str) -> float:
    """Parse an ISO 8601 datetime string to a Unix timestamp.

    - Empty string → returns current time (treat as "just created", no decay).
    - Malformed string → returns 0.0 (falsy) and logs a warning; the caller's
      ``if last_decayed_ts else 0`` guard then sets elapsed_weeks to 0.
    """
    if not iso:
        return time.time()
    try:
        dt = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=datetime.UTC).timestamp()
    except (ValueError, TypeError):
        _log.warning("Could not parse ISO timestamp %r; skipping decay for this pattern", iso)
        return 0.0
