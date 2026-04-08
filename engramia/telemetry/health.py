# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Deep health check probes for the Engramia API.

Each probe tests live connectivity to a backend component and returns a
dict with ``status``, ``latency_ms``, and optionally ``error``.

Called by the ``GET /v1/health/deep`` endpoint in ``api/routes.py``.
"""

from __future__ import annotations

import logging
import os
import time

_log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 5.0  # seconds — hard limit per probe

# The latest Alembic revision shipped with this version of the codebase.
# Update this constant whenever a new migration is added.
EXPECTED_MIGRATION_REVISION = "013"


def check_storage(storage) -> dict:
    """Probe storage backend connectivity.

    For PostgresStorage: executes ``SELECT 1``.
    For JSONStorage: counts keys (always succeeds).

    Args:
        storage: A StorageBackend instance.

    Returns:
        ``{"status": "ok"|"error", "latency_ms": float, "error": str|None}``
    """
    start = time.perf_counter()
    try:
        # PostgresStorage exposes _engine; JSONStorage does not.
        engine = getattr(storage, "_engine", None)
        if engine is not None:
            from sqlalchemy import text

            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        else:
            # JSONStorage — list keys is a cheap in-memory op
            storage.list_keys(prefix="metrics/")

        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        _log.warning("Storage health probe failed: %s", exc)
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": str(exc),
        }


def check_llm(llm) -> dict:
    """Probe LLM provider connectivity with a minimal call.

    Args:
        llm: An LLMProvider instance, or None.

    Returns:
        Probe result dict or ``{"status": "not_configured"}`` when llm is None.
    """
    if llm is None:
        return {"status": "not_configured"}

    start = time.perf_counter()
    try:
        # Use a trivially cheap prompt; real providers timeout at 30s
        llm.call("ping", system=None, role="default")
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        _log.warning("LLM health probe failed: %s", exc)
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": str(exc),
        }


def check_embedding(embeddings) -> dict:
    """Probe embedding provider connectivity.

    Args:
        embeddings: An EmbeddingProvider instance, or None.

    Returns:
        Probe result dict or ``{"status": "not_configured"}`` when None.
    """
    if embeddings is None:
        return {"status": "not_configured"}

    start = time.perf_counter()
    try:
        vec = embeddings.embed("health check")
        if not vec or not isinstance(vec, list):
            raise ValueError("Empty embedding returned")
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        _log.warning("Embedding health probe failed: %s", exc)
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": str(exc),
        }


def check_redis() -> dict:
    """Probe Redis connectivity.

    Redis is an optional component — Engramia uses in-process rate limiting by
    default and only requires Redis when ``ENGRAMIA_REDIS_URL`` is set (e.g.
    for multi-instance deployments that share rate-limit counters).

    Returns:
        Probe result dict, or ``{"status": "not_configured"}`` when Redis is
        not configured.
    """
    redis_url = os.environ.get("ENGRAMIA_REDIS_URL")
    if not redis_url:
        return {"status": "not_configured"}

    start = time.perf_counter()
    try:
        import redis as redis_lib  # type: ignore[import-untyped]

        client = redis_lib.from_url(redis_url, socket_connect_timeout=_PROBE_TIMEOUT, socket_timeout=_PROBE_TIMEOUT)
        client.ping()
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        _log.warning("Redis health probe failed: %s", exc)
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": str(exc),
        }


def check_stripe() -> dict:
    """Probe Stripe API reachability.

    Sends a lightweight HTTP HEAD request to ``https://api.stripe.com/v1/``
    with a short timeout.  Does not use the Stripe SDK or authenticate — this
    only verifies network-level reachability from the host running the API.

    Skipped when ``STRIPE_SECRET_KEY`` is not set.

    Returns:
        Probe result dict, or ``{"status": "not_configured"}`` when Stripe
        billing is not configured.
    """
    if not os.environ.get("STRIPE_SECRET_KEY"):
        return {"status": "not_configured"}

    start = time.perf_counter()
    try:
        import httpx

        httpx.head("https://api.stripe.com/v1/", timeout=_PROBE_TIMEOUT)
        return {"status": "ok", "latency_ms": round((time.perf_counter() - start) * 1000, 2)}
    except Exception as exc:
        _log.warning("Stripe reachability probe failed: %s", exc)
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": str(exc),
        }


def check_migration(storage) -> dict:
    """Verify the database migration version matches the expected revision.

    Only applicable to PostgresStorage.  For JSONStorage this is a no-op
    (returns ``not_configured``).

    Args:
        storage: A StorageBackend instance.

    Returns:
        ``{"status": "ok"|"error"|"not_configured", "latency_ms": float,
           "current_revision": str, "expected_revision": str}``
    """
    engine = getattr(storage, "_engine", None)
    if engine is None:
        return {"status": "not_configured"}

    start = time.perf_counter()
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()

        current = row[0] if row else None
        latency = round((time.perf_counter() - start) * 1000, 2)

        if current == EXPECTED_MIGRATION_REVISION:
            return {
                "status": "ok",
                "latency_ms": latency,
                "current_revision": current,
                "expected_revision": EXPECTED_MIGRATION_REVISION,
            }

        _log.warning(
            "Migration version mismatch: current=%s expected=%s",
            current,
            EXPECTED_MIGRATION_REVISION,
        )
        return {
            "status": "error",
            "latency_ms": latency,
            "current_revision": current,
            "expected_revision": EXPECTED_MIGRATION_REVISION,
            "error": f"Migration mismatch: current={current!r} expected={EXPECTED_MIGRATION_REVISION!r}",
        }
    except Exception as exc:
        _log.warning("Migration version probe failed: %s", exc)
        return {
            "status": "error",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "error": str(exc),
        }


def aggregate_status(checks: dict[str, dict]) -> str:
    """Derive overall status from individual probe results.

    Returns:
        ``"ok"`` if all probes succeeded,
        ``"degraded"`` if at least one failed,
        ``"error"`` if all non-skipped probes failed.
    """
    statuses = [v["status"] for v in checks.values() if v["status"] != "not_configured"]
    if not statuses:
        return "ok"
    if all(s == "ok" for s in statuses):
        return "ok"
    if all(s == "error" for s in statuses):
        return "error"
    return "degraded"
