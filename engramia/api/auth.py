# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Bearer token authentication for the Engramia API.

Authentication mode is controlled by the ``ENGRAMIA_AUTH_MODE`` environment
variable:

    auto (default)
        Use DB auth if ``ENGRAMIA_DATABASE_URL`` is configured and the
        ``api_keys`` table exists; fall back to env-var auth otherwise.
    env
        Always use env-var auth (``ENGRAMIA_API_KEYS`` comma-separated list).
        Backward-compatible with pre-5.2 deployments.
    db
        Always use DB auth. Fail with 503 if ``auth_engine`` is not on app state.
    dev
        No authentication. Requires ``ENGRAMIA_ALLOW_NO_AUTH=true`` as a
        deliberate safety acknowledgement.

DB auth mode:
    Keys are stored as SHA-256 hashes in the ``api_keys`` table. A successful
    lookup sets ``request.state.auth_context`` (AuthContext) and propagates the
    tenant/project scope via contextvars for downstream storage filtering.

Env-var auth mode (backward compat):
    Keys loaded from ``ENGRAMIA_API_KEYS``. Comparison uses
    ``hmac.compare_digest`` to prevent timing oracle attacks. Scope is always
    the default tenant/project.

Token comparison is always timing-safe.
"""

import hashlib
import hmac
import logging
import os
import threading
import time

from fastapi import HTTPException, Request, status

from engramia._context import set_scope
from engramia.types import AuthContext, Scope

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth mode
# ---------------------------------------------------------------------------

_AUTH_MODE = os.environ.get("ENGRAMIA_AUTH_MODE", "auto").lower()


def _use_db_auth() -> bool:
    """Return True when DB auth should be used for the current configuration."""
    if _AUTH_MODE == "env":
        return False
    if _AUTH_MODE == "db":
        return True
    if _AUTH_MODE == "dev":
        return False
    # "auto": use DB if DATABASE_URL is configured
    return bool(os.environ.get("ENGRAMIA_DATABASE_URL", "").strip())


# ---------------------------------------------------------------------------
# Env-var auth (backward compat)
# ---------------------------------------------------------------------------


def _load_api_keys() -> set[str]:
    raw = os.environ.get("ENGRAMIA_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def _env_auth(request: Request, token: str) -> None:
    """Validate token against ENGRAMIA_API_KEYS. Sets default scope on success."""
    api_keys = _load_api_keys()
    if not api_keys:
        # Dev mode — no keys configured, allow unauthenticated access.
        # Warning is emitted at startup by _log_security_config().
        return
    if not any(hmac.compare_digest(token, key) for key in api_keys):
        from engramia.api.audit import AuditEvent, log_event

        ip = request.client.host if request.client else "unknown"
        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    # Env-var auth always operates in the default scope.
    set_scope(Scope())


# ---------------------------------------------------------------------------
# DB auth
# ---------------------------------------------------------------------------


def _hash_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Simple in-process TTL cache: avoids a DB round-trip on every request.
# Entries are invalidated immediately on key revocation (see keys.py).
_key_cache: dict[str, tuple[float, dict | None]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 60.0  # seconds


def _db_lookup(engine, key_hash: str) -> dict | None:
    """Query the api_keys table for a valid, non-revoked, non-expired key."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, tenant_id, project_id, role, max_patterns "
                    "FROM api_keys "
                    "WHERE key_hash = :h "
                    "  AND revoked_at IS NULL "
                    "  AND (expires_at IS NULL OR expires_at > now()::text) "
                    "LIMIT 1"
                ),
                {"h": key_hash},
            ).fetchone()
    except Exception as exc:
        _log.error("DB auth lookup failed: %s", exc)
        return None

    if row is None:
        return None
    return {
        "id": str(row[0]),
        "tenant_id": str(row[1]),
        "project_id": str(row[2]),
        "role": str(row[3]),
        "max_patterns": row[4],
    }


def _lookup_key_cached(engine, key_hash: str) -> dict | None:
    """Return the key row from the cache or DB, respecting TTL."""
    now = time.monotonic()
    with _cache_lock:
        if key_hash in _key_cache:
            expires_at, row = _key_cache[key_hash]
            if now < expires_at:
                return row
            del _key_cache[key_hash]

    row = _db_lookup(engine, key_hash)
    with _cache_lock:
        _key_cache[key_hash] = (now + _CACHE_TTL, row)
    return row


def invalidate_key_cache(key_hash: str) -> None:
    """Immediately evict a key from the auth cache (call on revoke/rotate)."""
    with _cache_lock:
        _key_cache.pop(key_hash, None)


def _db_auth(request: Request, token: str, engine) -> None:
    """Validate token via DB lookup. Sets auth_context + scope on success."""
    key_hash = _hash_key(token)
    row = _lookup_key_cached(engine, key_hash)
    ip = request.client.host if request.client else "unknown"

    if row is None:
        from engramia.api.audit import AuditEvent, log_event

        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    scope = Scope(tenant_id=row["tenant_id"], project_id=row["project_id"])
    request.state.auth_context = AuthContext(
        key_id=row["id"],
        tenant_id=row["tenant_id"],
        project_id=row["project_id"],
        role=row["role"],
        max_patterns=row["max_patterns"],
        scope=scope,
    )
    set_scope(scope)


# ---------------------------------------------------------------------------
# Main FastAPI dependency
# ---------------------------------------------------------------------------


async def require_auth(request: Request) -> None:
    """FastAPI dependency that validates the Bearer token.

    Attach to a route or router with ``dependencies=[Depends(require_auth)]``.

    Behaviour by AUTH_MODE:
    - dev:  no auth (requires ENGRAMIA_ALLOW_NO_AUTH=true).
    - env:  validate against ENGRAMIA_API_KEYS; no-op if list is empty (dev mode).
    - db:   DB lookup; sets request.state.auth_context and scope contextvar.
    - auto: DB if ENGRAMIA_DATABASE_URL set, else env.
    """
    if _AUTH_MODE == "dev":
        if not os.environ.get("ENGRAMIA_ALLOW_NO_AUTH"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Dev auth mode requires ENGRAMIA_ALLOW_NO_AUTH=true to be set "
                    "as a deliberate safety acknowledgement."
                ),
            )
        return  # unauthenticated dev mode

    # Env-var auth with no keys configured → unauthenticated dev mode (backward compat).
    # Must check this before parsing the Authorization header so that existing
    # single-tenant deployments without ENGRAMIA_API_KEYS continue to work.
    if not _use_db_auth() and not _load_api_keys():
        return  # no keys configured — allow all requests (matches pre-5.2 behaviour)

    auth_header = request.headers.get("Authorization", "")
    ip = request.client.host if request.client else "unknown"

    if not auth_header.startswith("Bearer "):
        from engramia.api.audit import AuditEvent, log_event

        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="missing_or_malformed_header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <key>",
        )

    token = auth_header[len("Bearer "):]

    if _use_db_auth():
        engine = getattr(request.app.state, "auth_engine", None)
        if engine is None:
            _log.error("DB auth is enabled but auth_engine is not on app.state")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service not available.",
            )
        _db_auth(request, token, engine)
    else:
        _env_auth(request, token)
