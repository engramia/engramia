"""Tests for EngramiaWebhook SDK client."""

import json
from unittest.mock import patch

import pytest

from engramia.sdk.webhook import EngramiaWebhook, EngramiaWebhookError


class _FakeHeaders:
    """Fake headers dict for FakeResponse."""

    def get(self, name: str, default: str = "") -> str:
        if name == "Content-Type":
            return "application/json"
        return default


class FakeResponse:
    """Fake urllib response."""

    def __init__(self, data: dict, status: int = 200):
        self._data = json.dumps(data).encode()
        self.status = status
        self.headers = _FakeHeaders()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestEngramiaWebhook:
    """Tests for the webhook SDK client."""

    def _client(self, api_key=None):
        return EngramiaWebhook(url="http://localhost:8000", api_key=api_key)

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_learn(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"stored": True, "pattern_count": 5})
        client = self._client()

        result = client.learn(task="Parse CSV", code="import csv", eval_score=8.5)
        assert result["stored"] is True
        assert result["pattern_count"] == 5

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_recall(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"matches": [{"similarity": 0.95, "reuse_tier": "duplicate"}]})
        client = self._client()

        matches = client.recall(task="Parse CSV")
        assert len(matches) == 1
        assert matches[0]["similarity"] == 0.95

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_health(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"status": "ok", "storage": "JSONStorage"})
        client = self._client()

        result = client.health()
        assert result["status"] == "ok"

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_metrics(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"runs": 10, "success_rate": 0.9})
        client = self._client()

        result = client.metrics()
        assert result["runs"] == 10

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_delete_pattern(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"deleted": True})
        client = self._client()

        assert client.delete_pattern("patterns/abc_123") is True

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_run_aging(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"pruned": 3})
        client = self._client()

        assert client.run_aging() == 3

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_feedback(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"feedback": ["Add error handling"]})
        client = self._client()

        result = client.feedback(limit=3)
        assert result == ["Add error handling"]

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_auth_header_included(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"status": "ok"})
        client = self._client(api_key="secret-123")

        client.health()
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer secret-123"

    @patch("engramia.sdk.webhook.urllib.request.urlopen")
    def test_http_error_raises(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://localhost:8000/health",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )
        client = self._client()

        with pytest.raises(EngramiaWebhookError) as exc_info:
            client.health()
        assert exc_info.value.status_code == 401
