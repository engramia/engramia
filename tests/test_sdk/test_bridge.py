# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for EngramiaBridge — agent factory pre/post-run hooks."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from engramia.sdk.bridge import EngramiaBridge, _format_matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match(task="Parse CSV", score=8.5, sim=0.90, code="import csv"):
    """Build a match dict in the shape EngramiaWebhook returns."""
    return {
        "similarity": sim,
        "reuse_tier": "adapt",
        "pattern_key": "patterns/abc123",
        "pattern": {
            "task": task,
            "success_score": score,
            "design": {"code": code},
        },
    }


def _make_match_obj(task="Parse CSV", score=8.5, sim=0.90, code="import csv"):
    """Build a match as a Mock object (Memory-style)."""
    m = MagicMock()
    m.similarity = sim
    m.reuse_tier = "adapt"
    m.pattern_key = "patterns/abc123"
    m.pattern.task = task
    m.pattern.success_score = score
    m.pattern.design = {"code": code}
    return m


# ---------------------------------------------------------------------------
# _format_matches
# ---------------------------------------------------------------------------

class TestFormatMatches:
    def test_empty_returns_empty_string(self):
        assert _format_matches([]) == ""

    def test_dict_match_renders_markdown(self):
        result = _format_matches([_make_match(task="Load CSV", score=9.0, sim=0.88, code="df = pd.read_csv(f)")])
        assert "## Relevant patterns" in result
        assert "Load CSV" in result
        assert "score 9.0" in result
        assert "similarity 0.88" in result
        assert "df = pd.read_csv(f)" in result

    def test_object_match_renders_markdown(self):
        result = _format_matches([_make_match_obj(task="Z-score norm", score=7.0, sim=0.75)])
        assert "Z-score norm" in result
        assert "score 7.0" in result

    def test_multiple_matches_numbered(self):
        matches = [_make_match(task=f"Task {i}") for i in range(3)]
        result = _format_matches(matches)
        assert "### 1." in result
        assert "### 2." in result
        assert "### 3." in result

    def test_code_truncated_at_2000_chars(self):
        long_code = "x = 1\n" * 500  # > 2000 chars
        result = _format_matches([_make_match(code=long_code)])
        # The injected code block must be at most 2000 chars
        start = result.index("```python\n") + len("```python\n")
        end = result.index("\n```\n", start)
        assert end - start <= 2000


# ---------------------------------------------------------------------------
# EngramiaBridge — REST mode (api_url set)
# ---------------------------------------------------------------------------

class TestBridgeRestMode:
    """Bridge selects REST mode when api_url is provided."""

    def _bridge(self, **kwargs) -> EngramiaBridge:
        return EngramiaBridge(api_url="http://localhost:8000", api_key="sk-test", **kwargs)

    def test_recall_context_returns_markdown(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        mock_client.recall.return_value = [_make_match(task="Parse CSV")]
        bridge._client = mock_client

        result = bridge.recall_context("Read CSV file")
        assert "Parse CSV" in result
        mock_client.recall.assert_called_once_with(task="Read CSV file", limit=3)

    def test_recall_context_empty_when_no_matches(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        mock_client.recall.return_value = []
        bridge._client = mock_client

        assert bridge.recall_context("anything") == ""

    def test_recall_context_swallows_exception(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        mock_client.recall.side_effect = RuntimeError("network failure")
        bridge._client = mock_client

        result = bridge.recall_context("task")
        assert result == ""  # never raises

    def test_recall_context_custom_limit(self):
        bridge = self._bridge(recall_limit=5)
        mock_client = MagicMock()
        mock_client.recall.return_value = []
        bridge._client = mock_client

        bridge.recall_context("task", limit=2)
        mock_client.recall.assert_called_once_with(task="task", limit=2)

    def test_learn_run_calls_learn(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        bridge._client = mock_client

        bridge.learn_run(task="Parse CSV", code="import csv", output="ok", eval_score=8.0)
        mock_client.learn.assert_called_once_with(
            task="Parse CSV", code="import csv", eval_score=8.0, output="ok"
        )

    def test_learn_run_skips_below_min_score(self):
        bridge = self._bridge(min_score_to_learn=7.0)
        mock_client = MagicMock()
        bridge._client = mock_client

        bridge.learn_run(task="bad run", code="x", eval_score=4.0)
        mock_client.learn.assert_not_called()

    def test_learn_run_swallows_exception(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        mock_client.learn.side_effect = ConnectionError("server down")
        bridge._client = mock_client

        bridge.learn_run(task="task", code="x", eval_score=7.0)  # must not raise

    def test_learn_run_auto_evaluate_when_no_score(self):
        bridge = self._bridge(auto_evaluate=True)
        mock_client = MagicMock()
        mock_client.evaluate.return_value = {"median_score": 8.5}
        bridge._client = mock_client

        bridge.learn_run(task="task", code="x", output="out", eval_score=None)
        mock_client.evaluate.assert_called_once()
        # Learn should be called with the score returned by evaluate
        call_args = mock_client.learn.call_args
        assert call_args.kwargs["eval_score"] == 8.5

    def test_learn_run_no_auto_evaluate_uses_default(self):
        bridge = self._bridge(auto_evaluate=False)
        mock_client = MagicMock()
        bridge._client = mock_client

        bridge.learn_run(task="task", code="x", eval_score=None)
        mock_client.evaluate.assert_not_called()
        # Falls back to 6.0 conservative default
        call_args = mock_client.learn.call_args
        assert call_args.kwargs["eval_score"] == 6.0

    def test_auto_evaluate_fallback_on_error(self):
        bridge = self._bridge(auto_evaluate=True)
        mock_client = MagicMock()
        mock_client.evaluate.side_effect = RuntimeError("llm unavailable")
        bridge._client = mock_client

        bridge.learn_run(task="task", code="x", eval_score=None)
        # Should fall back to 6.0 and still call learn
        call_args = mock_client.learn.call_args
        assert call_args.kwargs["eval_score"] == 6.0

    def test_before_run_delegates_to_recall_context(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        mock_client.recall.return_value = [_make_match()]
        bridge._client = mock_client

        ctx = bridge.before_run("Parse CSV")
        assert "Parse CSV" in ctx

    def test_after_run_skips_when_success_false(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        bridge._client = mock_client

        bridge.after_run(task="failed task", code="x", success=False)
        mock_client.learn.assert_not_called()

    def test_after_run_records_when_success_true(self):
        bridge = self._bridge()
        mock_client = MagicMock()
        bridge._client = mock_client

        bridge.after_run(task="task", code="x", eval_score=7.0, success=True)
        mock_client.learn.assert_called_once()


# ---------------------------------------------------------------------------
# EngramiaBridge — wrap decorator
# ---------------------------------------------------------------------------

class TestBridgeWrapDecorator:
    def _bridge_with_mock_client(self, **kwargs) -> tuple[EngramiaBridge, MagicMock]:
        bridge = EngramiaBridge(api_url="http://localhost:8000", **kwargs)
        mock_client = MagicMock()
        mock_client.recall.return_value = [_make_match()]
        bridge._client = mock_client
        return bridge, mock_client

    def test_wrap_calls_before_and_after(self):
        bridge, mock_client = self._bridge_with_mock_client()

        @bridge.wrap
        def run_agent(task: str) -> dict:
            return {"code": "x = 1", "output": "1", "success": True, "eval_score": 8.0}

        run_agent(task="Compute stats")
        mock_client.recall.assert_called_once()
        mock_client.learn.assert_called_once()

    def test_wrap_injects_context_if_accepted(self):
        bridge, mock_client = self._bridge_with_mock_client()
        received_ctx: list[str] = []

        @bridge.wrap
        def run_agent(task: str, **kwargs) -> dict:
            received_ctx.append(kwargs.get("_engramia_context", ""))
            return {"code": "x", "success": True}

        run_agent(task="Compute stats")
        assert received_ctx[0] != ""  # context was injected

    def test_wrap_skips_context_if_not_accepted(self):
        bridge, mock_client = self._bridge_with_mock_client()

        @bridge.wrap
        def run_agent(task: str) -> dict:
            return {"code": "x", "success": True}

        # Should not raise TypeError about unexpected _engramia_context kwarg
        run_agent(task="task")

    def test_wrap_skips_learn_when_success_false(self):
        bridge, mock_client = self._bridge_with_mock_client()

        @bridge.wrap
        def run_agent(task: str) -> dict:
            return {"code": "x", "success": False}

        run_agent(task="task")
        mock_client.learn.assert_not_called()

    def test_wrap_positional_task_arg(self):
        bridge, mock_client = self._bridge_with_mock_client()

        @bridge.wrap
        def run_agent(task: str) -> dict:
            return {"code": "x", "success": True, "eval_score": 7.0}

        run_agent("Parse CSV")  # positional
        mock_client.recall.assert_called_once_with(task="Parse CSV", limit=3)

    def test_wrap_custom_task_arg_name(self):
        bridge, mock_client = self._bridge_with_mock_client()

        @bridge.wrap(task_arg="query")
        def run_agent(query: str) -> dict:
            return {"code": "x", "success": True, "eval_score": 7.0}

        run_agent(query="Find emails")
        mock_client.recall.assert_called_once_with(task="Find emails", limit=3)

    def test_wrap_preserves_return_value(self):
        bridge, _ = self._bridge_with_mock_client()

        @bridge.wrap
        def run_agent(task: str) -> dict:
            return {"code": "x = 42", "output": "42", "success": True}

        result = run_agent(task="Compute")
        assert result["code"] == "x = 42"
        assert result["output"] == "42"


# ---------------------------------------------------------------------------
# EngramiaBridge — mode selection (lazy client init)
# ---------------------------------------------------------------------------

class TestBridgeModeSelection:
    def test_rest_mode_when_api_url_provided(self):
        # bridge.py does a lazy `from engramia.sdk.webhook import EngramiaWebhook`
        # inside _get_client(), so we patch at the source module.
        bridge = EngramiaBridge(api_url="http://api.engramia.dev", api_key="sk-x")
        with patch("engramia.sdk.webhook.EngramiaWebhook") as MockWebhook:
            MockWebhook.return_value = MagicMock()
            _ = bridge._get_client()
            MockWebhook.assert_called_once_with(url="http://api.engramia.dev", api_key="sk-x")

    def test_direct_mode_when_no_api_url(self):
        # Similarly, patch the lazy imports at their source modules.
        bridge = EngramiaBridge(api_url=None, data_path="/tmp/brain")
        with (
            patch("engramia.Memory") as MockMemory,
            patch("engramia._factory.make_embeddings", return_value=MagicMock()),
            patch("engramia._factory.make_storage", return_value=MagicMock()),
            patch("engramia._factory.make_llm", return_value=MagicMock()),
        ):
            MockMemory.return_value = MagicMock()
            _ = bridge._get_client()
            MockMemory.assert_called_once()

    def test_client_cached_after_first_call(self):
        bridge = EngramiaBridge(api_url="http://localhost:8000")
        mock_client = MagicMock()
        mock_client.recall.return_value = []
        bridge._client = mock_client

        c1 = bridge._get_client()
        c2 = bridge._get_client()
        assert c1 is c2
