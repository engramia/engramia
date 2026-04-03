# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""API key management endpoints.

All endpoints require DB auth mode (ENGRAMIA_AUTH_MODE=db or auto with DB).
Attempting to call these in env-var auth mode returns 503.

Key lifecycle::

    POST /v1/keys/bootstrap  — create the very first owner key (empty table only)
    POST /v1/keys            — create a key (admin+)
    GET  /v1/keys            — list keys for current project (admin+)
    DELETE /v1/keys/{key_id} — revoke a key (admin+)
    POST /v1/keys/{key_id}/rotate — rotate a key, returns new secret (admin+)

Key format::

    engramia_sk_<43 base64url chars>   (total ~55 chars)

Only the SHA-256 hash is stored in the DB. The full key is shown exactly once
on creation or rotation and cannot be recovered afterwards.
"""

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from engramia.api.audit import AuditEvent, log_db_event, log_event
from engramia.api.auth import invalidate_key_cache, require_auth
from engramia.api.permissions import require_permission

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/keys", tags=["keys"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class KeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: Literal["owner", "admin", "editor", "reader"] = "editor"
    max_patterns: int | None = Field(default=None, ge=1, le=1_000_000)
    expires_at: str | None = None  # ISO-8601 text, NULL = never expires


class KeyCreateResponse(BaseModel):
    id: str
    name: str
    key: str  # full secret — shown once only
    key_prefix: str
    role: str
    tenant_id: str
    project_id: str
    max_patterns: int | None
    created_at: str


class KeyInfo(BaseModel):
    id: str
    name: str
    key_prefix: str
    role: str
    tenant_id: str
    project_id: str
    max_patterns: int | None
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    expires_at: str | None


class KeyListResponse(BaseModel):
    keys: list[KeyInfo]


class KeyRevokeResponse(BaseModel):
    id: str
    revoked: bool


class KeyRotateResponse(BaseModel):
    id: str
    key: str  # new full secret — shown once only
    key_prefix: str


class BootstrapRequest(BaseModel):
    tenant_name: str = Field(default="Default", min_length=1, max_length=100)
    project_name: str = Field(default="default", min_length=1, max_length=100)
    key_name: str = Field(default="Owner key", min_length=1, max_length=100)
    bootstrap_token: str | None = Field(default=None, description="Must match ENGRAMIA_BOOTSTRAP_TOKEN.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_engine(request: Request):
    engine = getattr(request.app.state, "auth_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Key management requires DB auth mode (ENGRAMIA_DATABASE_URL must be configured).",
        )
    return engine


def _generate_key() -> tuple[str, str, str]:
    """Return (full_key, display_prefix, sha256_hash)."""
    suffix = secrets.token_urlsafe(32)  # 43 base64url chars
    full_key = f"engramia_sk_{suffix}"
    display_prefix = f"engramia_sk_{suffix[:8]}..."
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, display_prefix, key_hash


def _create_key_in_db(
    engine,
    *,
    tenant_id: str,
    project_id: str,
    name: str,
    role: str,
    max_patterns: int | None,
    expires_at: str | None,
) -> KeyCreateResponse:
    from sqlalchemy import text

    full_key, display_prefix, key_hash = _generate_key()
    key_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, tenant_id, project_id, name, key_prefix, key_hash, role, max_patterns, created_at, expires_at) "
                "VALUES (:id, :tid, :pid, :name, :prefix, :hash, :role, :max_p, now()::text, :exp)"
            ),
            {
                "id": key_id,
                "tid": tenant_id,
                "pid": project_id,
                "name": name,
                "prefix": display_prefix,
                "hash": key_hash,
                "role": role,
                "max_p": max_patterns,
                "exp": expires_at,
            },
        )
        row = conn.execute(
            text("SELECT created_at FROM api_keys WHERE id = :id"),
            {"id": key_id},
        ).fetchone()

    return KeyCreateResponse(
        id=key_id,
        name=name,
        key=full_key,
        key_prefix=display_prefix,
        role=role,
        tenant_id=tenant_id,
        project_id=project_id,
        max_patterns=max_patterns,
        created_at=str(row[0]) if row else "",
    )


# ---------------------------------------------------------------------------
# Bootstrap (no auth required — only works on empty api_keys table)
# ---------------------------------------------------------------------------


@router.post(
    "/bootstrap",
    response_model=KeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create the first owner key",
    description=(
        "One-time bootstrap endpoint. Only works when the ``api_keys`` table "
        "is empty. Creates (or reuses) the default tenant and project, then "
        "issues an owner-role API key. Once any key exists, this endpoint "
        "returns 409 Conflict.\n\n"
        "Requires ``ENGRAMIA_BOOTSTRAP_TOKEN`` to be set in the server environment. "
        "The same value must be supplied as ``bootstrap_token`` in the request body. "
        "Remove the env var after first use to disable the endpoint permanently."
    ),
)
def bootstrap(body: BootstrapRequest, request: Request) -> KeyCreateResponse:
    engine = _require_engine(request)

    # ------------------------------------------------------------------
    # B: Token guard — endpoint is disabled unless ENGRAMIA_BOOTSTRAP_TOKEN
    # is explicitly configured.  Validate with timing-safe compare.
    # ------------------------------------------------------------------
    expected_token = os.environ.get("ENGRAMIA_BOOTSTRAP_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Bootstrap is disabled. Set ENGRAMIA_BOOTSTRAP_TOKEN in the server "
                "environment and supply it as 'bootstrap_token' in the request body."
            ),
        )
    supplied = (body.bootstrap_token or "").strip()
    if not hmac.compare_digest(supplied.encode(), expected_token.encode()):
        ip = request.client.host if request.client else "unknown"
        _log.warning("Bootstrap attempt with invalid token from %s", ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bootstrap token.",
        )

    from sqlalchemy import text

    # ------------------------------------------------------------------
    # A: Atomic race-condition guard — acquire a DB-level advisory lock so
    # that concurrent bootstrap calls are serialised.  The count check and
    # all inserts happen inside the same transaction; the lock is released
    # automatically at transaction end.
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        # Exclusive session-level advisory lock (arbitrary stable integer).
        conn.execute(text("SELECT pg_advisory_xact_lock(7369726d616e)"))

        count = conn.execute(text("SELECT COUNT(*) FROM api_keys")).fetchone()
        if count and int(count[0]) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bootstrap already completed. Use an existing admin/owner key to create more keys.",
            )

        # Ensure default tenant + project exist inside the same transaction.
        conn.execute(
            text(
                "INSERT INTO tenants (id, name) VALUES ('default', :name) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
            ),
            {"name": body.tenant_name},
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, tenant_id, name) VALUES ('default', 'default', :pname) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"pname": body.project_name},
        )

        # Create the owner key inside the same locked transaction.
        full_key, display_prefix, key_hash = _generate_key()
        key_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, tenant_id, project_id, name, key_prefix, key_hash, role, max_patterns, created_at, expires_at) "
                "VALUES (:id, 'default', 'default', :name, :prefix, :hash, 'owner', NULL, now()::text, NULL)"
            ),
            {
                "id": key_id,
                "name": body.key_name,
                "prefix": display_prefix,
                "hash": key_hash,
            },
        )
        row = conn.execute(
            text("SELECT created_at FROM api_keys WHERE id = :id"),
            {"id": key_id},
        ).fetchone()

    result = KeyCreateResponse(
        id=key_id,
        name=body.key_name,
        key=full_key,
        key_prefix=display_prefix,
        role="owner",
        tenant_id="default",
        project_id="default",
        max_patterns=None,
        created_at=str(row[0]) if row else "",
    )
    log_event(AuditEvent.KEY_CREATED, key_id=result.id, role="owner", source="bootstrap")
    _log.info("Bootstrap complete — owner key created: %s", result.key_prefix)
    return result


# ---------------------------------------------------------------------------
# Create key
# ---------------------------------------------------------------------------


_ROLE_RANK: dict[str, int] = {"reader": 0, "editor": 1, "admin": 2, "owner": 3}
# Maximum role that each caller role may assign to a new key.
_MAX_ASSIGNABLE: dict[str, str] = {
    "owner": "owner",
    "admin": "editor",   # admin cannot escalate to admin/owner
    "editor": "reader",  # should never reach here — editor lacks keys:create
    "reader": "reader",  # should never reach here — reader lacks keys:create
}


@router.post(
    "",
    response_model=KeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_auth), require_permission("keys:create")],
    summary="Create a new API key",
)
def create_key(body: KeyCreateRequest, request: Request) -> KeyCreateResponse:
    engine = _require_engine(request)
    ctx = request.state.auth_context  # guaranteed by require_auth + DB mode

    # Enforce role hierarchy: callers cannot grant roles higher than they are
    # allowed to assign.  Owners may assign any role; admins max out at editor.
    caller_rank = _ROLE_RANK.get(ctx.role, 0)
    requested_rank = _ROLE_RANK.get(body.role, 0)
    max_assignable = _MAX_ASSIGNABLE.get(ctx.role, "reader")
    max_rank = _ROLE_RANK[max_assignable]
    if requested_rank > max_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Role '{ctx.role}' may assign at most '{max_assignable}' keys. "
                f"Requested role '{body.role}' is not permitted."
            ),
        )

    result = _create_key_in_db(
        engine,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        name=body.name,
        role=body.role,
        max_patterns=body.max_patterns,
        expires_at=body.expires_at,
    )
    ip = request.client.host if request.client else "unknown"
    log_event(AuditEvent.KEY_CREATED, key_id=result.id, role=body.role, ip=ip)
    log_db_event(
        engine,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        key_id=ctx.key_id,
        action="key_created",
        resource_type="api_key",
        resource_id=result.id,
        ip_address=ip,
    )
    return result


# ---------------------------------------------------------------------------
# List keys
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=KeyListResponse,
    dependencies=[Depends(require_auth), require_permission("keys:list")],
    summary="List API keys for the current project",
)
def list_keys(request: Request) -> KeyListResponse:
    engine = _require_engine(request)
    ctx = request.state.auth_context

    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, name, key_prefix, role, tenant_id, project_id, "
                "max_patterns, created_at, last_used_at, revoked_at, expires_at "
                "FROM api_keys "
                "WHERE tenant_id = :tid AND project_id = :pid "
                "ORDER BY created_at DESC"
            ),
            {"tid": ctx.tenant_id, "pid": ctx.project_id},
        ).fetchall()

    keys = [
        KeyInfo(
            id=str(r[0]),
            name=str(r[1]),
            key_prefix=str(r[2]),
            role=str(r[3]),
            tenant_id=str(r[4]),
            project_id=str(r[5]),
            max_patterns=r[6],
            created_at=str(r[7]),
            last_used_at=str(r[8]) if r[8] else None,
            revoked_at=str(r[9]) if r[9] else None,
            expires_at=str(r[10]) if r[10] else None,
        )
        for r in rows
    ]
    return KeyListResponse(keys=keys)


# ---------------------------------------------------------------------------
# Revoke key
# ---------------------------------------------------------------------------


@router.delete(
    "/{key_id}",
    response_model=KeyRevokeResponse,
    dependencies=[Depends(require_auth), require_permission("keys:revoke")],
    summary="Revoke an API key",
)
def revoke_key(key_id: str, request: Request) -> KeyRevokeResponse:
    engine = _require_engine(request)
    ctx = request.state.auth_context

    from sqlalchemy import text

    # Fetch key to verify it belongs to the caller's project + get its hash
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT key_hash, revoked_at FROM api_keys "
                "WHERE id = :id AND tenant_id = :tid AND project_id = :pid"
            ),
            {"id": key_id, "tid": ctx.tenant_id, "pid": ctx.project_id},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")
    if row[1] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Key is already revoked.")

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE api_keys SET revoked_at = now()::text WHERE id = :id"),
            {"id": key_id},
        )

    # Evict from auth cache immediately
    invalidate_key_cache(str(row[0]))

    ip = request.client.host if request.client else "unknown"
    log_event(AuditEvent.KEY_REVOKED, key_id=key_id, ip=ip)
    log_db_event(
        engine,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        key_id=ctx.key_id,
        action="key_revoked",
        resource_type="api_key",
        resource_id=key_id,
        ip_address=ip,
    )
    return KeyRevokeResponse(id=key_id, revoked=True)


# ---------------------------------------------------------------------------
# Rotate key
# ---------------------------------------------------------------------------


@router.post(
    "/{key_id}/rotate",
    response_model=KeyRotateResponse,
    dependencies=[Depends(require_auth), require_permission("keys:rotate")],
    summary="Rotate an API key",
    description=(
        "Generates a new secret for the key and immediately revokes the old one. "
        "The new secret is returned exactly once — store it securely."
    ),
)
def rotate_key(key_id: str, request: Request) -> KeyRotateResponse:
    engine = _require_engine(request)
    ctx = request.state.auth_context

    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT key_hash, revoked_at FROM api_keys "
                "WHERE id = :id AND tenant_id = :tid AND project_id = :pid"
            ),
            {"id": key_id, "tid": ctx.tenant_id, "pid": ctx.project_id},
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")
    if row[1] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot rotate a revoked key.")

    old_hash = str(row[0])
    full_key, display_prefix, new_hash = _generate_key()

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE api_keys "
                "SET key_hash = :new_hash, key_prefix = :new_prefix, last_used_at = NULL "
                "WHERE id = :id"
            ),
            {"new_hash": new_hash, "new_prefix": display_prefix, "id": key_id},
        )

    # Evict old key from auth cache immediately
    invalidate_key_cache(old_hash)

    ip = request.client.host if request.client else "unknown"
    log_event(AuditEvent.KEY_ROTATED, key_id=key_id, ip=ip)
    log_db_event(
        engine,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        key_id=ctx.key_id,
        action="key_rotated",
        resource_type="api_key",
        resource_id=key_id,
        ip_address=ip,
    )
    return KeyRotateResponse(id=key_id, key=full_key, key_prefix=display_prefix)
