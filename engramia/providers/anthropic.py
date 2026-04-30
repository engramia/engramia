# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Anthropic/Claude LLM provider.

Requires the ``anthropic`` extra:
    pip install engramia[anthropic]

Uses lazy imports so the module can be imported without the ``anthropic``
package installed — the ImportError is raised at instantiation.

BYOK update (Phase 6.6): ``api_key`` is a constructor parameter. When
omitted, the anthropic SDK falls back to the ``ANTHROPIC_API_KEY`` env
var, preserving backward compatibility for self-hosted single-tenant
deployments. The cloud factory passes the plaintext key resolved by
:class:`engramia.credentials.resolver.CredentialResolver`.
"""

import logging
import random
import threading
import time

from engramia.providers._concurrency import llm_semaphore
from engramia.providers.base import LLMProvider
from engramia.telemetry import metrics as _metrics
from engramia.telemetry import tracing as _tracing

_log = logging.getLogger(__name__)

_ANTHROPIC_INSTALL_MSG = (
    "Anthropic provider requires the anthropic package. Install it with: pip install engramia[anthropic]"
)


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic Messages API.

    Handles retries with exponential backoff and jitter.
    Does not retry on authentication, permission, or bad-request errors.

    Args:
        model: Model ID to use (default: ``claude-sonnet-4-6``).
        max_retries: Number of attempts before raising the last exception.
        max_tokens: Maximum tokens in the response (default: 4096).
        timeout: Per-request timeout in seconds.
        api_key: Optional explicit key (BYOK path). Falls back to
            ``ANTHROPIC_API_KEY`` env var when None.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        max_retries: int = 3,
        max_tokens: int = 4096,
        timeout: float = 30.0,
        *,
        api_key: str | None = None,
    ) -> None:
        try:
            from anthropic import Anthropic

            kwargs: dict = {"timeout": timeout}
            if api_key is not None:
                kwargs["api_key"] = api_key
            self._client = Anthropic(**kwargs)
        except ImportError:
            raise ImportError(_ANTHROPIC_INSTALL_MSG) from None
        self._model = model
        self._max_retries = max_retries
        self._max_tokens = max_tokens
        # Thread-local last-call usage for the cost-ceiling meter (#2b).
        # See OpenAIProvider for the full rationale.
        self._tls = threading.local()

    @_tracing.traced("llm.call", {"llm.provider": "anthropic"})
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
        t0 = time.perf_counter()
        with llm_semaphore():
            for attempt in range(self._max_retries):
                try:
                    response = self._client.messages.create(**kwargs)
                    _metrics.observe_llm("anthropic", self._model, time.perf_counter() - t0, role)
                    usage = getattr(response, "usage", None)
                    tls = getattr(self, "_tls", None)
                    if usage is not None and tls is not None:
                        tls.last_usage = {
                            "tokens_in": int(getattr(usage, "input_tokens", 0) or 0),
                            "tokens_out": int(getattr(usage, "output_tokens", 0) or 0),
                        }
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
                        time.sleep(2**attempt + random.uniform(0, 1))

        raise last_exc or RuntimeError(f"All {self._max_retries} retries exhausted with no exception recorded")
