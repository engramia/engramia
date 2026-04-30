# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Per-tenant connection limiter for hosted MCP.

Enforces the concurrent-session caps from the pricing matrix:

    Team        ->  5 concurrent sessions
    Business    -> 25
    Enterprise  -> 100

Tiers below Team cannot open hosted MCP at all (rejected one layer up by
:func:`tier_satisfies` against :data:`MIN_TIER_FOR_HOSTED_MCP`).

The default backend is in-process (:class:`InMemoryConnectionLimiter`) and
fits the current single-replica deploy on Hetzner CX23. The
:class:`ConnectionLimiter` Protocol exists so a future Redis backend can be
swapped in via ``ENGRAMIA_MCP_LIMITER_BACKEND=redis`` without changing the
call sites in ``http_server.py``. See ADR-005 in the architecture doc.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from engramia.mcp.errors import ConnectionLimitExceeded

_log = logging.getLogger(__name__)

# Default caps per tier — overridable via env vars at construction time so
# operators can tune in staging without code changes.
DEFAULT_TIER_LIMITS: dict[str, int] = {
    "team": 5,
    "business": 25,
    "enterprise": 100,
}


@dataclass
class AcquiredSlot:
    """Token returned by :meth:`ConnectionLimiter.acquire`. Pass back to
    :meth:`ConnectionLimiter.release` (or call its own ``release``) to free
    the slot. Re-using a released slot is a programming error.
    """

    tenant_id: str
    plan_tier: str
    _released: bool = False
    _release_callback: object = None  # set by limiter; opaque to caller

    async def release(self) -> None:
        """Idempotent — calling twice is a no-op."""
        if self._released:
            return
        self._released = True
        cb = self._release_callback
        if cb is not None:
            await cb()  # type: ignore[misc]


class ConnectionLimiter(Protocol):
    """Backend interface for per-tenant connection slot enforcement."""

    async def acquire(self, tenant_id: str, plan_tier: str) -> AcquiredSlot:
        """Reserve one concurrent-session slot for *tenant_id*.

        Raises:
            ConnectionLimitExceeded: when the tenant has already reached its
                tier-defined maximum.
            ValueError: when *plan_tier* has no configured limit (i.e. a
                tier below ``team`` slipped past the upstream gate).
        """

    async def release(self, slot: AcquiredSlot) -> None:
        """Free a previously-acquired slot. Idempotent."""

    def active_count(self, tenant_id: str) -> int:
        """Number of currently-held slots for the tenant — for /metrics."""

    def cap_for(self, plan_tier: str) -> int:
        """Configured cap for the tier."""


class InMemoryConnectionLimiter:
    """Single-process limiter using one :class:`asyncio.Lock` plus per-tenant
    counters.

    Why not :class:`asyncio.Semaphore`: a semaphore blocks waiters until a
    slot frees up. We want to *fail fast* with HTTP 429 when over capacity,
    not queue an indefinite wait that ties up uvicorn workers. So a counter
    plus an explicit cap check is a better fit.
    """

    def __init__(self, tier_limits: dict[str, int] | None = None) -> None:
        self._limits = dict(tier_limits) if tier_limits else dict(DEFAULT_TIER_LIMITS)
        self._lock = asyncio.Lock()
        self._counts: dict[str, int] = {}

    def cap_for(self, plan_tier: str) -> int:
        return self._limits.get(plan_tier, 0)

    def active_count(self, tenant_id: str) -> int:
        return self._counts.get(tenant_id, 0)

    async def acquire(self, tenant_id: str, plan_tier: str) -> AcquiredSlot:
        cap = self.cap_for(plan_tier)
        if cap <= 0:
            raise ValueError(
                f"No connection limit configured for plan_tier={plan_tier!r}; "
                "this tier is not allowed to open hosted MCP. The tier gate "
                "should reject earlier — this is a programming error."
            )

        async with self._lock:
            current = self._counts.get(tenant_id, 0)
            if current >= cap:
                raise ConnectionLimitExceeded(
                    tenant_id=tenant_id,
                    plan_tier=plan_tier,
                    used=current,
                    cap=cap,
                )
            self._counts[tenant_id] = current + 1

        slot = AcquiredSlot(tenant_id=tenant_id, plan_tier=plan_tier)

        async def _release() -> None:
            async with self._lock:
                remaining = self._counts.get(tenant_id, 0) - 1
                if remaining <= 0:
                    self._counts.pop(tenant_id, None)
                else:
                    self._counts[tenant_id] = remaining

        slot._release_callback = _release  # type: ignore[assignment]
        _log.debug(
            "MCP slot acquired tenant=%s tier=%s used=%d cap=%d",
            tenant_id,
            plan_tier,
            current + 1,
            cap,
        )
        return slot

    async def release(self, slot: AcquiredSlot) -> None:
        await slot.release()


def make_limiter_from_env(env: dict[str, str]) -> ConnectionLimiter:
    """Construct a limiter from environment variables.

    Reads:
        ENGRAMIA_MCP_LIMITER_BACKEND  inmemory | redis  (default: inmemory)
        ENGRAMIA_MCP_LIMITS_TEAM       int   (default: 5)
        ENGRAMIA_MCP_LIMITS_BUSINESS   int   (default: 25)
        ENGRAMIA_MCP_LIMITS_ENTERPRISE int   (default: 100)

    The ``redis`` backend is reserved for a future implementation (ADR-005);
    requesting it today raises :class:`NotImplementedError`.
    """
    backend = env.get("ENGRAMIA_MCP_LIMITER_BACKEND", "inmemory").lower()
    limits = {
        "team": int(env.get("ENGRAMIA_MCP_LIMITS_TEAM", "5")),
        "business": int(env.get("ENGRAMIA_MCP_LIMITS_BUSINESS", "25")),
        "enterprise": int(env.get("ENGRAMIA_MCP_LIMITS_ENTERPRISE", "100")),
    }
    if backend == "inmemory":
        return InMemoryConnectionLimiter(tier_limits=limits)
    if backend == "redis":  # pragma: no cover  — future work
        raise NotImplementedError(
            "Redis-backed connection limiter is planned (ADR-005) but not "
            "yet implemented. Use ENGRAMIA_MCP_LIMITER_BACKEND=inmemory."
        )
    raise ValueError(f"Unknown ENGRAMIA_MCP_LIMITER_BACKEND={backend!r}")
