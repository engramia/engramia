# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Tests for engramia.mcp.tier_gate — per-tenant connection limiter.

Covers:
- Slot acquire / release semantics on the in-memory backend.
- Cap enforcement raises ConnectionLimitExceeded with correct used/cap.
- Idempotent slot release.
- Limiter picks correct cap per tier (5 / 25 / 100 default).
- make_limiter_from_env reads env-var overrides.
- Unknown tier raises ValueError (defensive — caller should reject earlier).
- Redis backend not implemented yet.
"""

import pytest

from engramia.mcp.errors import ConnectionLimitExceeded
from engramia.mcp.tier_gate import (
    DEFAULT_TIER_LIMITS,
    InMemoryConnectionLimiter,
    make_limiter_from_env,
)


@pytest.mark.asyncio
async def test_default_caps_match_pricing_matrix():
    assert DEFAULT_TIER_LIMITS == {"team": 5, "business": 25, "enterprise": 100}


@pytest.mark.asyncio
async def test_acquire_then_release_frees_slot():
    lim = InMemoryConnectionLimiter()
    slot = await lim.acquire("tenant-A", "team")
    assert lim.active_count("tenant-A") == 1
    await slot.release()
    assert lim.active_count("tenant-A") == 0


@pytest.mark.asyncio
async def test_acquire_cap_team_is_5():
    lim = InMemoryConnectionLimiter()
    slots = [await lim.acquire("t", "team") for _ in range(5)]
    assert lim.active_count("t") == 5
    with pytest.raises(ConnectionLimitExceeded) as exc_info:
        await lim.acquire("t", "team")
    assert exc_info.value.used == 5
    assert exc_info.value.cap == 5
    assert exc_info.value.plan_tier == "team"
    # Cleanup so test isolation holds even on failure
    for s in slots:
        await s.release()


@pytest.mark.asyncio
async def test_release_is_idempotent():
    lim = InMemoryConnectionLimiter()
    slot = await lim.acquire("t", "team")
    await slot.release()
    await slot.release()  # second call is a no-op
    assert lim.active_count("t") == 0


@pytest.mark.asyncio
async def test_releases_decrement_counter_independently_per_tenant():
    lim = InMemoryConnectionLimiter()
    a = await lim.acquire("alpha", "team")
    b = await lim.acquire("beta", "team")
    assert lim.active_count("alpha") == 1
    assert lim.active_count("beta") == 1
    await a.release()
    assert lim.active_count("alpha") == 0
    assert lim.active_count("beta") == 1
    await b.release()


@pytest.mark.asyncio
async def test_unknown_tier_raises_value_error():
    lim = InMemoryConnectionLimiter()
    with pytest.raises(ValueError, match="No connection limit"):
        await lim.acquire("t", "developer")


@pytest.mark.asyncio
async def test_business_cap_is_25():
    lim = InMemoryConnectionLimiter()
    assert lim.cap_for("business") == 25


@pytest.mark.asyncio
async def test_enterprise_cap_is_100():
    lim = InMemoryConnectionLimiter()
    assert lim.cap_for("enterprise") == 100


@pytest.mark.asyncio
async def test_make_limiter_from_env_inmemory_default():
    lim = make_limiter_from_env({})
    assert isinstance(lim, InMemoryConnectionLimiter)
    assert lim.cap_for("team") == 5


@pytest.mark.asyncio
async def test_make_limiter_from_env_overrides_caps():
    lim = make_limiter_from_env(
        {
            "ENGRAMIA_MCP_LIMITS_TEAM": "3",
            "ENGRAMIA_MCP_LIMITS_BUSINESS": "10",
            "ENGRAMIA_MCP_LIMITS_ENTERPRISE": "50",
        }
    )
    assert lim.cap_for("team") == 3
    assert lim.cap_for("business") == 10
    assert lim.cap_for("enterprise") == 50


def test_make_limiter_from_env_redis_not_implemented():
    with pytest.raises(NotImplementedError):
        make_limiter_from_env({"ENGRAMIA_MCP_LIMITER_BACKEND": "redis"})


def test_make_limiter_from_env_unknown_backend_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        make_limiter_from_env({"ENGRAMIA_MCP_LIMITER_BACKEND": "memcached"})
