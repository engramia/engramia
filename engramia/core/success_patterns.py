# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Success pattern lifecycle management.

Handles time-based decay (aging) and reuse tracking on top of the patterns
already stored by Memory.learn(). Not a separate storage — operates directly
on the "patterns/" namespace of the StorageBackend.

Decay rate: 2% per week (DECAY_PER_WEEK = 0.98).
Prune threshold: MIN_SCORE = 0.1.
Reuse boost: +0.1 score per reuse, capped at 10.0.
"""

import logging
import time

from engramia._util import PATTERNS_PREFIX
from engramia.providers.base import StorageBackend
from engramia.types import Pattern

_log = logging.getLogger(__name__)

_DECAY_PER_WEEK = 0.98
_MIN_SCORE = 0.1
_REUSE_BOOST = 0.1


class SuccessPatternStore:
    """Manages aging and reuse tracking for stored patterns.

    Args:
        storage: Storage backend that holds the "patterns/" namespace.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def mark_reused(self, pattern_key: str) -> None:
        """Increment reuse_count and boost success_score for a pattern.

        Called by the reuse engine when a pattern is selected for adaptation
        or direct reuse. Boosts score to reward proven patterns.

        Args:
            pattern_key: Full storage key (e.g. "patterns/abc123_1234").
        """
        data = self._storage.load(pattern_key)
        if data is None:
            return
        pattern = Pattern.model_validate(data)
        updated = pattern.model_copy(
            update={
                "reuse_count": pattern.reuse_count + 1,
                "success_score": min(10.0, pattern.success_score + _REUSE_BOOST),
            }
        )
        save_data = updated.model_dump()
        # Preserve internal metadata fields (e.g. _author_key_id)
        for k, v in data.items():
            if k.startswith("_") and k not in save_data:
                save_data[k] = v
        self._storage.save(pattern_key, save_data)

    def run_aging(self) -> int:
        """Apply time-based decay to all stored patterns.

        Each pattern's success_score is multiplied by 0.98 per elapsed week.
        Patterns whose decayed score falls below 0.1 are removed permanently.

        Returns:
            Number of patterns pruned.
        """
        keys = self._storage.list_keys(prefix=PATTERNS_PREFIX)
        now = time.time()
        pruned = 0

        for key in keys:
            data = self._storage.load(key)
            if data is None:
                continue
            pattern = Pattern.model_validate(data)
            # Clamp to 0 to handle accidental future timestamps without inflating scores
            elapsed_weeks = max(0.0, (now - pattern.timestamp) / (7 * 24 * 3600))
            decayed = pattern.success_score * (_DECAY_PER_WEEK**elapsed_weeks)

            if decayed < _MIN_SCORE:
                self._storage.delete(key)
                pruned += 1
            else:
                # Preserve the original creation timestamp — resetting it to now
                # would make elapsed_weeks = 0 on the next run, halting all decay.
                updated = pattern.model_copy(update={"success_score": round(decayed, 4)})
                save_data = updated.model_dump()
                # Preserve internal metadata fields (e.g. _author_key_id)
                for k, v in data.items():
                    if k.startswith("_") and k not in save_data:
                        save_data[k] = v
                self._storage.save(key, save_data)

        return pruned

    def get_count(self) -> int:
        """Return the total number of stored patterns."""
        return len(self._storage.list_keys(prefix=PATTERNS_PREFIX))
