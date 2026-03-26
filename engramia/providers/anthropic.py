# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Anthropic/Claude LLM provider.

Requires the ``anthropic`` extra:
    pip install agent-brain[anthropic]

Uses lazy imports so the module can be imported without the ``anthropic``
package installed — the ImportError is raised at instantiation.
"""

import logging
import time

from engramia.providers.base import LLMProvider

_log = logging.getLogger(__name__)

_ANTHROPIC_INSTALL_MSG = (
    "Anthropic provider requires the anthropic package. Install it with: pip install agent-brain[anthropic]"
)

#: Errors that should not be retried (client-side mistakes).
_NO_RETRY_STATUS = {400, 401, 403}


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic Messages API.

    Handles retries with exponential backoff and jitter.
    Does not retry on authentication, permission, or bad-request errors.

    Args:
        model: Model ID to use (default: ``claude-sonnet-4-20250514``).
        max_retries: Number of attempts before raising the last exception.
        max_tokens: Maximum tokens in the response (default: 4096).
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_retries: int = 3,
        max_tokens: int = 4096,
    ) -> None:
        try:
            from anthropic import Anthropic

            self._client = Anthropic()
        except ImportError:
            raise ImportError(_ANTHROPIC_INSTALL_MSG) from None
        self._model = model
        self._max_retries = max_retries
        self._max_tokens = max_tokens

    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        from anthropic import (
            AuthenticationError,
            BadRequestError,
            PermissionDeniedError,
        )

        messages: list[dict] = [{"role": "user", "content": prompt}]

        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.messages.create(**kwargs)
                # Extract text from the first content block
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return ""
            except (AuthenticationError, BadRequestError, PermissionDeniedError):
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    _log.warning(
                        "Anthropic call failed (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries,
                        exc,
                    )
                    time.sleep(2**attempt)

        raise last_exc or RuntimeError(f"All {self._max_retries} retries exhausted with no exception recorded")
