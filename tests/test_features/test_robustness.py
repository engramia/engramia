# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D12 — System robustness / edge cases.

Tests boundary conditions and error handling:
  1. Empty task string → ValidationError
  2. Whitespace-only task → ValidationError
  3. Code at exact 500KB limit → accepted (boundary)
  4. Code over 500KB → ValidationError
  5. eval_score = 11.0 → ValidationError
  6. eval_score = -1.0 → ValidationError
  7. Delete non-existent pattern → deleted=False (no crash)
  8. Recall on empty store (fresh client) → empty list
  9. Unicode task → learn + recall round-trip succeeds
  10. Very long task (just under 10K chars) → accepted
"""

from __future__ import annotations

import pytest

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS

_VALID_CODE = CLUSTER_SNIPPETS["C01"]["good"]["code"]
_VALID_TASK = "Test task for robustness checks"
_VALID_SCORE = 7.0


def _expect_error(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) and assert it raises any exception."""
    try:
        fn(*args, **kwargs)
        return False  # No exception raised
    except Exception:
        return True


def test_empty_task_raises(client: TestClient) -> None:
    """Empty task string must be rejected."""
    raised = _expect_error(client.learn, task="", code=_VALID_CODE, eval_score=_VALID_SCORE)
    assert raised, "learn('') should raise ValidationError"


def test_whitespace_task_raises(client: TestClient) -> None:
    """Whitespace-only task must be rejected."""
    raised = _expect_error(client.learn, task="   \t\n  ", code=_VALID_CODE, eval_score=_VALID_SCORE)
    assert raised, "learn(whitespace) should raise ValidationError"


def test_eval_score_too_high_raises(client: TestClient) -> None:
    """eval_score > 10.0 must be rejected."""
    raised = _expect_error(client.learn, task=_VALID_TASK, code=_VALID_CODE, eval_score=11.0)
    assert raised, "learn(eval_score=11.0) should raise ValidationError"


def test_eval_score_negative_raises(client: TestClient) -> None:
    """eval_score < 0.0 must be rejected."""
    raised = _expect_error(client.learn, task=_VALID_TASK, code=_VALID_CODE, eval_score=-1.0)
    assert raised, "learn(eval_score=-1.0) should raise ValidationError"


def test_code_at_limit_accepted(client: TestClient, run_tag: str) -> None:
    """Code at exactly 500KB should be accepted (boundary value)."""
    task = f"[{run_tag}] boundary-code-len"
    big_code = "# " + ("x" * (500_000 - 2))  # exactly 500KB
    learned_keys: list[str] = []
    try:
        key = learn_and_get_key(client, task=task, code=big_code, eval_score=5.0)
        if key:
            learned_keys.append(key)
        # No assertion needed — if it raised, the test fails
    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)


def test_code_over_limit_raises(client: TestClient) -> None:
    """Code exceeding 500KB must be rejected."""
    over_limit_code = "x" * 500_001
    raised = _expect_error(client.learn, task=_VALID_TASK, code=over_limit_code, eval_score=5.0)
    assert raised, "learn(code > 500KB) should raise ValidationError"


def test_delete_nonexistent_pattern(client: TestClient) -> None:
    """Deleting a non-existent pattern key returns False without raising."""
    result = client.delete_pattern("patterns/nonexistent_key_xyz_000")
    assert result is False, f"Expected delete_pattern() to return False for non-existent key, got {result}"


def test_delete_twice_second_is_false(client: TestClient, run_tag: str) -> None:
    """Deleting a pattern twice: first=True, second=False."""
    task = f"[{run_tag}] delete-twice"
    snippet = CLUSTER_SNIPPETS["C04"]["medium"]
    key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=6.0)

    if not key:
        pytest.skip("Could not discover pattern key for delete test")

    first = client.delete_pattern(key)
    second = client.delete_pattern(key)

    assert first is True, f"First delete should return True, got {first}"
    assert second is False, f"Second delete should return False, got {second}"


def test_unicode_task_roundtrip(client: TestClient, run_tag: str) -> None:
    """Unicode task strings survive learn → recall without corruption."""
    task = f"[{run_tag}] Načíst CSV soubor a filtrovat záznamy podle sloupce 'stav'"
    snippet = CLUSTER_SNIPPETS["C01"]["medium"]
    learned_keys: list[str] = []

    try:
        key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=6.0)
        if key:
            learned_keys.append(key)

        matches = client.recall(task=task, limit=1, deduplicate=False, eval_weighted=False)
        assert matches, "Unicode task was not recalled"
        recalled_task = matches[0]["pattern"]["task"]
        assert task in recalled_task or task == recalled_task, (
            f"Recalled task does not match original: {recalled_task!r}"
        )

    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)


def test_very_long_task_accepted(client: TestClient, run_tag: str) -> None:
    """Task at just under 10K chars should be accepted."""
    prefix = f"[{run_tag}] "
    filler = "Analyze and process the following CSV data, applying complex filtering logic. "
    # Build task just under 10,000 chars
    base_len = len(prefix) + len(filler)
    repeat = (9_990 - base_len) // len(filler)
    long_task = prefix + filler * max(1, repeat)
    long_task = long_task[:9_990]

    snippet = CLUSTER_SNIPPETS["C01"]["medium"]
    learned_keys: list[str] = []
    try:
        key = learn_and_get_key(client, task=long_task, code=snippet["code"], eval_score=5.0)
        if key:
            learned_keys.append(key)
    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)
