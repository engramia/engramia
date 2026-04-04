# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Shared fixtures and constants for the test_api suite.

Provides:
- EVAL_RESPONSE / COMPOSE_RESPONSE  — fixed LLM responses for deterministic tests
- mock_llm                           — MagicMock LLM returning EVAL_RESPONSE
- _reset_scope                       — autouse: resets scope contextvar after each
                                       test so analytics dependency_overrides don't
                                       bleed across test boundaries
"""
import json
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared LLM response constants
# ---------------------------------------------------------------------------

EVAL_RESPONSE = json.dumps(
    {
        "task_alignment": 8,
        "code_quality": 7,
        "workspace_usage": 8,
        "robustness": 6,
        "overall": 7.5,
        "feedback": "Add error handling for missing input files.",
    }
)

COMPOSE_RESPONSE = json.dumps(
    {
        "stages": [
            {"task": "Read CSV file", "reads": ["input.csv"], "writes": ["data.json"]},
            {"task": "Compute statistics", "reads": ["data.json"], "writes": ["report.txt"]},
        ]
    }
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    """MagicMock LLM whose .call() returns a fixed evaluator JSON response."""
    llm = MagicMock()
    llm.call.return_value = EVAL_RESPONSE
    return llm


@pytest.fixture(autouse=True)
def _reset_scope():
    """Reset the scope contextvar after every test in test_api/.

    analytics tests use dependency_overrides that call set_scope(Scope()).
    set_scope() returns a Token that can be used to restore the previous state.
    We capture the pre-test token here and reset it after the test so the
    contextvar is always back to the pre-test value.

    Note: set_scope(Scope()) leaks Scope(tenant_id='default', ...) which is
    identical to the LookupError fallback value — functionally a no-op — but
    explicit cleanup prevents confusion when reading test output.
    """
    from engramia._context import _scope_var
    from engramia.types import Scope

    # Snapshot the current contextvar state by setting a known value and keeping
    # the token. This token lets us restore the *exact* previous state (set or unset).
    snapshot_token = _scope_var.set(Scope())
    yield
    _scope_var.reset(snapshot_token)
