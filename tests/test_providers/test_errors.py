# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Direct tests for ``engramia.providers._errors.is_auth_error``.

The classifier is mocked at every other call site (failover tests). This
module exercises it head-on against real SDK exception instances so a
classification regression — for example, a new SDK version that introduces
a sub-class of AuthenticationError that our isinstance() chain doesn't
catch — fails loudly instead of silently routing auth errors through
failover.
"""

from __future__ import annotations

import pytest

from engramia.providers._errors import is_auth_error


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# OpenAI SDK
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_module("openai"), reason="openai SDK not installed")
class TestOpenAIClassification:
    def _make(self, cls):
        # All openai.*Error subclasses accept (message, response, body).
        # Pass the minimum fields to construct a real instance — we only
        # need isinstance() to work.
        from unittest.mock import Mock

        mock_response = Mock()
        mock_response.request = Mock()
        return cls("test", response=mock_response, body=None)

    def test_authentication_error_is_auth(self):
        from openai import AuthenticationError

        assert is_auth_error(self._make(AuthenticationError)) is True

    def test_permission_denied_error_is_auth(self):
        from openai import PermissionDeniedError

        assert is_auth_error(self._make(PermissionDeniedError)) is True

    def test_bad_request_error_is_auth(self):
        from openai import BadRequestError

        assert is_auth_error(self._make(BadRequestError)) is True

    def test_rate_limit_is_NOT_auth(self):
        # Rate limits are intentionally treated as transient so failover
        # to the next provider in the chain happens on quota exhaustion.
        from openai import RateLimitError

        assert is_auth_error(self._make(RateLimitError)) is False

    def test_internal_server_error_is_NOT_auth(self):
        from openai import InternalServerError

        assert is_auth_error(self._make(InternalServerError)) is False


# ---------------------------------------------------------------------------
# Anthropic SDK
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_module("anthropic"), reason="anthropic SDK not installed")
class TestAnthropicClassification:
    def _make(self, cls):
        from unittest.mock import Mock

        mock_response = Mock()
        mock_response.request = Mock()
        return cls(message="test", response=mock_response, body=None)

    def test_authentication_error_is_auth(self):
        from anthropic import AuthenticationError

        assert is_auth_error(self._make(AuthenticationError)) is True

    def test_permission_denied_error_is_auth(self):
        from anthropic import PermissionDeniedError

        assert is_auth_error(self._make(PermissionDeniedError)) is True

    def test_bad_request_error_is_auth(self):
        from anthropic import BadRequestError

        assert is_auth_error(self._make(BadRequestError)) is True

    def test_rate_limit_is_NOT_auth(self):
        from anthropic import RateLimitError

        assert is_auth_error(self._make(RateLimitError)) is False


# ---------------------------------------------------------------------------
# Generic / fallback
# ---------------------------------------------------------------------------


class TestFallback:
    def test_plain_exception_is_NOT_auth(self):
        assert is_auth_error(Exception("plain")) is False

    def test_value_error_is_NOT_auth(self):
        assert is_auth_error(ValueError("oops")) is False

    def test_timeout_error_is_NOT_auth(self):
        assert is_auth_error(TimeoutError("slow")) is False

    def test_connection_error_is_NOT_auth(self):
        # Network errors must trigger failover, never fail-fast.
        assert is_auth_error(ConnectionError("refused")) is False
