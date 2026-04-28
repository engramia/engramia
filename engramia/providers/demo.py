# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Demo LLM provider for tenants without a configured BYOK credential.

Returned by :func:`engramia._factory.make_llm` when
:meth:`engramia.credentials.resolver.CredentialResolver.resolve` returns
``None`` — i.e. the tenant clicked "Skip for now" in onboarding, or their
key was revoked / marked invalid.

Behaviour:

- :meth:`DemoProvider.call` returns a deterministic JSON response when
  ``role="eval"`` so :class:`engramia.eval.evaluator.MultiEvaluator` can
  parse a valid eval result; for other roles, returns a plain-text demo
  message. Both responses tell the tenant to add an LLM key.
- :class:`DemoMeter` enforces a 50-call-per-month-per-tenant cap so this
  cannot be abused as a free LLM substitute. Counters are in-memory
  (process-local, calendar-month boundaries) — restart resets, which is
  acceptable for a demo path. A persistent DB-backed meter would be
  required only if abuse becomes evident in production telemetry.

The Memory facade and route handlers detect demo mode by inspecting
``isinstance(provider, DemoProvider)``; the API surfaces ``"mode": "demo"``
in response metadata so the dashboard can render the persistent
"Add your LLM key" banner.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from typing import Final

from engramia.exceptions import QuotaExceededError
from engramia.providers.base import LLMProvider

_log = logging.getLogger(__name__)

_DEMO_CALL_LIMIT: Final[int] = 50  # per tenant per calendar month

_DEMO_FEEDBACK = (
    "DEMO MODE — add your LLM API key in Settings -> LLM Providers to get "
    "real evaluations. This score is a placeholder."
)

_DEMO_DEFAULT = (
    "DEMO RESPONSE — add your LLM API key in Settings -> LLM Providers to "
    "enable real LLM features. Engramia returned this canned text because "
    "no provider key is configured for your tenant."
)


def _demo_eval_response() -> str:
    """Return a deterministic JSON eval result that MultiEvaluator can parse.

    Scores are middle-of-the-road (~6-7) so the demo run looks plausible
    and the variance / adversarial detectors stay neutral.
    """
    return json.dumps(
        {
            "task_alignment": 7,
            "code_quality": 7,
            "workspace_usage": 7,
            "robustness": 6,
            "overall": 6.8,
            "feedback": _DEMO_FEEDBACK,
        }
    )


class DemoMeter:
    """Process-local monthly counter of demo calls per tenant.

    Thread-safe via :class:`threading.Lock`. Calendar-month boundary in
    UTC: counters auto-reset at the start of a new month without an
    explicit reset call.

    Singleton instance available as ``DemoMeter.instance``. Tests can
    construct fresh meters and inject them via the patch helper exposed
    at module level.
    """

    _instance: DemoMeter | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._counters: dict[tuple[str, str], int] = {}  # (tenant_id, year_month) -> count
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> DemoMeter:
        """Return the process-wide singleton, creating it on first call."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @staticmethod
    def _current_period() -> str:
        """Return ``YYYY-MM`` for the current UTC calendar month."""
        now = datetime.datetime.now(datetime.UTC)
        return f"{now.year:04d}-{now.month:02d}"

    def try_increment(self, tenant_id: str) -> bool:
        """Reserve one demo call for ``tenant_id`` if under the cap.

        Returns:
            True if the call is permitted (counter incremented),
            False if the tenant has already used the monthly quota.
        """
        period = self._current_period()
        key = (tenant_id, period)
        with self._lock:
            current = self._counters.get(key, 0)
            if current >= _DEMO_CALL_LIMIT:
                return False
            self._counters[key] = current + 1
            return True

    def get_count(self, tenant_id: str) -> int:
        """Return how many demo calls this tenant has used this month."""
        with self._lock:
            return self._counters.get((tenant_id, self._current_period()), 0)

    def reset(self) -> None:
        """Drop all counters. Intended for tests only."""
        with self._lock:
            self._counters.clear()


class DemoProvider(LLMProvider):
    """LLM provider that returns canned responses with a demo-mode hint.

    Used as the fallback when a tenant has no active credential. Tracks
    invocations via :class:`DemoMeter` so abuse is bounded; raises
    :class:`engramia.exceptions.QuotaExceededError` when the monthly cap
    is reached so the route handler returns HTTP 429 with a clear
    "add your LLM key" message.

    Args:
        meter: Optional explicit meter instance. Defaults to the process
            singleton. Tests pass a fresh instance to isolate counts.
    """

    def __init__(self, meter: DemoMeter | None = None) -> None:
        self._meter = meter or DemoMeter.instance()

    def call(
        self,
        prompt: str,
        system: str | None = None,
        role: str = "default",
    ) -> str:
        # Resolve the active tenant for the meter. Imported at call time
        # to avoid a circular import (engramia._context -> types).
        from engramia._context import get_scope

        tenant_id = get_scope().tenant_id

        if not self._meter.try_increment(tenant_id):
            raise QuotaExceededError(
                "Demo mode quota exhausted "
                f"({_DEMO_CALL_LIMIT} calls / month). "
                "Add your LLM API key in Settings -> LLM Providers to continue."
            )

        if role == "eval":
            return _demo_eval_response()
        return _DEMO_DEFAULT
