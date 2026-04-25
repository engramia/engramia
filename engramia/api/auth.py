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
    oidc
        Validate OIDC JWTs issued by a standards-compliant identity provider
        (Okta, Auth0, Azure AD, Keycloak, …). Requires ``engramia[oidc]`` extra
        and ``ENGRAMIA_OIDC_ISSUER`` + ``ENGRAMIA_OIDC_AUDIENCE`` env vars.
        See ``engramia/api/oidc.py`` for full configuration reference.
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
    if _AUTH_MODE in ("env", "dev", "oidc"):
        return False
    if _AUTH_MODE == "db":
        return True
    # "auto": use DB if DATABASE_URL is configured
    return bool(os.environ.get("ENGRAMIA_DATABASE_URL", "").strip())


# ---------------------------------------------------------------------------
# Env-var auth (backward compat)
# ---------------------------------------------------------------------------


def _load_api_keys() -> set[str]:
    raw = os.environ.get("ENGRAMIA_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def _env_auth(request: Request, token: str) -> None:
    """Validate token against ENGRAMIA_API_KEYS. Sets default scope + auth_context on success."""
    api_keys = _load_api_keys()
    if not any(hmac.compare_digest(token, key) for key in api_keys):
        from engramia.api.audit import AuditEvent, log_event

        ip = request.client.host if request.client else "unknown"
        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    # Env-var auth operates in the default scope.
    scope = Scope()
    set_scope(scope)
    # Assign a role so that RBAC is enforced even in env-var mode.
    # Default is 'owner' for backward compatibility with single-key deployments;
    # override with ENGRAMIA_ENV_AUTH_ROLE=reader|editor|admin|owner.
    env_role = os.environ.get("ENGRAMIA_ENV_AUTH_ROLE", "owner").lower()
    valid_roles = {"owner", "admin", "editor", "reader"}
    if env_role not in valid_roles:
        _log.warning(
            "ENGRAMIA_ENV_AUTH_ROLE=%r is not a valid role %s — falling back to 'owner'.",
            env_role,
            valid_roles,
        )
        env_role = "owner"
    request.state.auth_context = AuthContext(
        key_id="env-key",
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        role=env_role,
        scope=scope,
    )


# ---------------------------------------------------------------------------
# DB auth
# ---------------------------------------------------------------------------


def _hash_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# In-process TTL cache with bounded size: avoids a DB round-trip on every request.
# LRU eviction (via OrderedDict) prevents DoS via unbounded growth from unique invalid keys.
# Entries are invalidated immediately on key revocation (see keys.py).
import collections  # noqa: E402

_key_cache: collections.OrderedDict[str, tuple[float, dict | None]] = collections.OrderedDict()
_cache_lock = threading.Lock()
_CACHE_TTL = 60.0  # seconds
_CACHE_MAX = 4096  # max entries before LRU eviction


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
    """Return the key row from the cache or DB, respecting TTL and LRU capacity."""
    now = time.monotonic()
    with _cache_lock:
        if key_hash in _key_cache:
            expires_at, row = _key_cache[key_hash]
            if now < expires_at:
                # Move to end (most recently used)
                _key_cache.move_to_end(key_hash)
                return row
            del _key_cache[key_hash]

    row = _db_lookup(engine, key_hash)
    with _cache_lock:
        _key_cache[key_hash] = (now + _CACHE_TTL, row)
        # Evict oldest entry when over capacity
        while len(_key_cache) > _CACHE_MAX:
            _key_cache.popitem(last=False)
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
# Cloud auth JWT — Dashboard sessions hit /v1/* with the JWT issued by
# /auth/login. We accept it as an alternate to the api_key Bearer token so
# the entire admin UI can rely on a single credential.
# ---------------------------------------------------------------------------


def _cloud_jwt_auth(request: Request, token: str) -> None:
    """Validate a cloud-auth JWT and build an AuthContext from its claims.

    Reuses cloud_auth._decode_token for signature, expiry and revocation
    checks. Looks up the tenant's auto-provisioned 'default' project so the
    Scope contextvar isolates queries correctly.
    """
    from engramia.api.audit import AuditEvent, log_event
    from engramia.api.cloud_auth import _decode_token

    ip = request.client.host if request.client else "unknown"
    try:
        payload = _decode_token(token)
    except HTTPException:
        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="invalid_jwt")
        raise

    tenant_id = payload["tenant_id"]
    project_id: str | None = None

    engine = getattr(request.app.state, "auth_engine", None)
    if engine is not None:
        try:
            from sqlalchemy import text

            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT id FROM projects WHERE tenant_id = :tid AND name = 'default' LIMIT 1"),
                    {"tid": tenant_id},
                ).fetchone()
            if row is not None:
                project_id = str(row[0])
        except Exception as exc:
            _log.warning("Cloud JWT auth: project lookup failed for tenant=%s: %s", tenant_id, exc)

    if project_id is None:
        # Fall back to a synthetic identifier so scope filtering remains tenant-
        # tight even when the project row is missing. Most v1 endpoints only
        # consult tenant_id, so failing closed at request time would surprise
        # a freshly-registered user mid-session.
        project_id = f"default-{tenant_id}"

    scope = Scope(tenant_id=tenant_id, project_id=project_id)
    request.state.auth_context = AuthContext(
        key_id=f"cloud:{payload['sub']}",
        tenant_id=tenant_id,
        project_id=project_id,
        role=payload.get("role", "owner"),
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
        allow_no_auth = os.environ.get("ENGRAMIA_ALLOW_NO_AUTH", "").lower() in ("true", "1", "yes")
        if not allow_no_auth:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Dev auth mode requires ENGRAMIA_ALLOW_NO_AUTH=true to be set "
                    "as a deliberate safety acknowledgement."
                ),
            )
        env = os.environ.get("ENGRAMIA_ENV", "").lower().strip()
        if env in ("production", "prod"):
            _log.critical(
                "CRITICAL: ENGRAMIA_ALLOW_NO_AUTH=true is set in a production environment (%r). "
                "Authentication cannot be disabled in production. "
                "Unset ENGRAMIA_ALLOW_NO_AUTH or change ENGRAMIA_AUTH_MODE.",
                env,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication cannot be disabled in a production environment.",
            )
        _log.warning(
            "SECURITY: Dev auth mode active — all requests are unauthenticated "
            "(ENGRAMIA_ALLOW_NO_AUTH=true). Do not use this in production."
        )
        return  # unauthenticated dev mode

    # Env-var auth with no keys configured: require explicit opt-in via ENGRAMIA_ALLOW_NO_AUTH.
    if not _use_db_auth() and not _load_api_keys():
        allow_no_auth = os.environ.get("ENGRAMIA_ALLOW_NO_AUTH", "").lower() in ("true", "1", "yes")
        if not allow_no_auth:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "No API keys configured. Set ENGRAMIA_API_KEYS, use ENGRAMIA_AUTH_MODE=db, "
                    "or set ENGRAMIA_ALLOW_NO_AUTH=true to explicitly allow unauthenticated access."
                ),
            )
        env = os.environ.get("ENGRAMIA_ENV", "").lower().strip()
        if env in ("production", "prod"):
            _log.critical(
                "CRITICAL: ENGRAMIA_ALLOW_NO_AUTH=true is set in a production environment (%r) "
                "with no API keys configured. Authentication cannot be disabled in production.",
                env,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication cannot be disabled in a production environment.",
            )
        _log.warning(
            "SECURITY: No API keys configured — request allowed without authentication "
            "(ENGRAMIA_ALLOW_NO_AUTH=true). Do not use this in production."
        )
        return

    auth_header = request.headers.get("Authorization", "")
    ip = request.client.host if request.client else "unknown"

    if not auth_header.startswith("Bearer "):
        from engramia.api.audit import AuditEvent, log_event

        log_event(AuditEvent.AUTH_FAILURE, ip=ip, reason="missing_or_malformed_header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. Expected: Bearer <key>",
        )

    token = auth_header[len("Bearer ") :]

    if _AUTH_MODE == "oidc":
        from engramia.api.oidc import oidc_auth

        oidc_auth(request, token)
    elif token.startswith("eyJ"):
        # Cloud-auth JWT issued by /auth/login or /auth/oauth. Dashboard
        # forwards it as Bearer for every /v1/* call. Recognise the standard
        # base64url JWT header prefix and dispatch to the cloud-aware path —
        # api_keys issued by /v1/keys all start with "engramia-" so the two
        # token shapes never collide.
        _cloud_jwt_auth(request, token)
    elif _use_db_auth():
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
