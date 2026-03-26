"""Tests for AnthropicProvider (mocked, no API key needed)."""

import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_provider(mock_client):
    """Create an AnthropicProvider with a mock client, bypassing __init__."""
    from agent_brain.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = mock_client
    provider._model = "claude-sonnet-4-20250514"
    provider._max_retries = 3
    provider._max_tokens = 4096
    return provider


def _mock_response(text="Hello, world!"):
    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = text
    mock_response.content = [mock_block]
    return mock_response


# Create a fake anthropic module with the exception classes
_fake_anthropic = MagicMock()
_fake_anthropic.AuthenticationError = type("AuthenticationError", (Exception,), {})
_fake_anthropic.BadRequestError = type("BadRequestError", (Exception,), {})
_fake_anthropic.PermissionDeniedError = type("PermissionDeniedError", (Exception,), {})


@pytest.fixture(autouse=True)
def _mock_anthropic_module():
    """Ensure the anthropic module is available for import."""
    with patch.dict(sys.modules, {"anthropic": _fake_anthropic}):
        yield


class TestAnthropicProvider:
    """Tests for the Anthropic LLM provider."""

    def test_call_returns_text(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("Hello, world!")
        provider = _make_provider(mock_client)

        result = provider.call("test prompt")
        assert result == "Hello, world!"

    def test_call_with_system_prompt(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("response")
        provider = _make_provider(mock_client)

        provider.call("prompt", system="Be helpful")
        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "Be helpful"

    def test_call_without_system_prompt(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_response("response")
        provider = _make_provider(mock_client)

        provider.call("prompt")
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" not in call_kwargs

    def test_retries_on_transient_error(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [
            ConnectionError("timeout"),
            _mock_response("success"),
        ]
        provider = _make_provider(mock_client)

        result = provider.call("test")
        assert result == "success"
        assert mock_client.messages.create.call_count == 2

    def test_raises_after_all_retries_exhausted(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = ConnectionError("always fails")
        provider = _make_provider(mock_client)
        provider._max_retries = 2

        with pytest.raises(ConnectionError, match="always fails"):
            provider.call("test")

    def test_does_not_retry_auth_error(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _fake_anthropic.AuthenticationError("bad key")
        provider = _make_provider(mock_client)

        with pytest.raises(Exception, match="bad key"):
            provider.call("test")
        assert mock_client.messages.create.call_count == 1
