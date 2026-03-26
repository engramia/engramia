"""Unit tests for EngramiaWebhook — mocks urllib to avoid live HTTP calls."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from engramia.sdk.webhook import EngramiaWebhook, EngramiaWebhookError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(body: dict, status: int = 200, content_type: str = "application/json"):
    """Build a mock urllib response."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(body).encode()
    resp.headers = MagicMock()
    resp.headers.get.return_value = content_type
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _hook(response_body: dict) -> EngramiaWebhook:
    """Return a EngramiaWebhook whose HTTP calls always return *response_body*."""
    hook = EngramiaWebhook(url="http://brain.local", api_key="sk-test")
    hook._request = MagicMock(return_value=response_body)
    return hook


# ---------------------------------------------------------------------------
# Existing methods (smoke-test the _request plumbing)
# ---------------------------------------------------------------------------


class TestExistingMethods:
    def test_learn(self):
        hook = _hook({"stored": True, "pattern_count": 1})
        result = hook.learn(task="Parse CSV", code="import csv", eval_score=8.0)
        assert result["stored"] is True
        hook._request.assert_called_once_with(
            "POST", "/v1/learn", {"task": "Parse CSV", "code": "import csv", "eval_score": 8.0}
        )

    def test_recall_returns_matches(self):
        hook = _hook({"matches": [{"similarity": 0.9}]})
        matches = hook.recall(task="Read CSV")
        assert matches == [{"similarity": 0.9}]

    def test_run_aging(self):
        hook = _hook({"pruned": 3})
        assert hook.run_aging() == 3

    def test_run_feedback_decay(self):
        hook = _hook({"pruned": 1})
        assert hook.run_feedback_decay() == 1


# ---------------------------------------------------------------------------
# Phase 3 methods
# ---------------------------------------------------------------------------


class TestEvolvePrompt:
    def test_returns_full_response(self):
        expected = {
            "improved_prompt": "You are an expert coder.",
            "changes": ["Added error handling guidance"],
            "issues_addressed": ["Missing error handling"],
            "accepted": True,
            "reason": "candidate_generated",
        }
        hook = _hook(expected)
        result = hook.evolve_prompt(
            role="coder",
            current_prompt="You are a coder.",
            num_issues=3,
        )
        assert result == expected
        hook._request.assert_called_once_with(
            "POST",
            "/v1/evolve",
            {
                "role": "coder",
                "current_prompt": "You are a coder.",
                "num_issues": 3,
            },
        )

    def test_default_num_issues(self):
        hook = _hook(
            {"improved_prompt": "p", "changes": [], "issues_addressed": [], "accepted": False, "reason": "no_issues"}
        )
        hook.evolve_prompt(role="coder", current_prompt="You are a coder.")
        _, _, body = hook._request.call_args.args
        assert body["num_issues"] == 5


class TestAnalyzeFailures:
    def test_returns_clusters(self):
        clusters = [{"representative": "Missing error handling", "members": [], "total_count": 5, "avg_score": 0.7}]
        hook = _hook({"clusters": clusters})
        result = hook.analyze_failures(min_count=2)
        assert result == clusters
        hook._request.assert_called_once_with("POST", "/v1/analyze-failures", {"min_count": 2})

    def test_empty_clusters(self):
        hook = _hook({"clusters": []})
        assert hook.analyze_failures() == []

    def test_default_min_count(self):
        hook = _hook({"clusters": []})
        hook.analyze_failures()
        _, _, body = hook._request.call_args.args
        assert body["min_count"] == 1


class TestRegisterSkills:
    def test_returns_registered_count(self):
        hook = _hook({"registered": 2})
        count = hook.register_skills(pattern_key="patterns/abc123", skills=["csv", "stats"])
        assert count == 2
        hook._request.assert_called_once_with(
            "POST",
            "/v1/skills/register",
            {
                "pattern_key": "patterns/abc123",
                "skills": ["csv", "stats"],
            },
        )

    def test_missing_registered_defaults_to_zero(self):
        hook = _hook({})
        assert hook.register_skills(pattern_key="patterns/abc", skills=["x"]) == 0


class TestFindBySkills:
    def test_returns_matches(self):
        matches = [{"similarity": 1.0, "reuse_tier": "duplicate", "pattern_key": "patterns/abc", "pattern": {}}]
        hook = _hook({"matches": matches})
        result = hook.find_by_skills(required=["csv"], match_all=True)
        assert result == matches
        hook._request.assert_called_once_with(
            "POST",
            "/v1/skills/search",
            {
                "required": ["csv"],
                "match_all": True,
            },
        )

    def test_match_all_false(self):
        hook = _hook({"matches": []})
        hook.find_by_skills(required=["csv", "stats"], match_all=False)
        _, _, body = hook._request.call_args.args
        assert body["match_all"] is False

    def test_empty_results(self):
        hook = _hook({})
        assert hook.find_by_skills(required=["unknown"]) == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_http_error_raises_webhook_error(self):
        import urllib.error

        hook = EngramiaWebhook(url="http://brain.local", api_key="sk-test")
        exc = urllib.error.HTTPError(
            url=None, code=401, msg="Unauthorized", hdrs=None, fp=BytesIO(b'{"detail":"bad key"}')
        )
        with patch("urllib.request.urlopen", side_effect=exc), pytest.raises(EngramiaWebhookError) as exc_info:
            hook.learn(task="t", code="c", eval_score=5.0)
        assert exc_info.value.status_code == 401

    def test_connection_error_raises_webhook_error(self):
        import urllib.error

        hook = EngramiaWebhook(url="http://brain.local")
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")),
            pytest.raises(EngramiaWebhookError) as exc_info,
        ):
            hook.health()
        assert exc_info.value.status_code == 0
        assert "Connection failed" in str(exc_info.value)
