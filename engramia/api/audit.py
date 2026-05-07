# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Structured audit logging for the Engramia API.

Audit events cover security-relevant operations that should be traceable.
Events are emitted to the ``engramia.audit`` logger at WARNING level for
machine-parseable audit trails via standard log aggregation.

In DB auth mode, events are additionally written to the ``audit_log`` table
via ``log_db_event()`` (called from key management routes).

Usage::

    from engramia.api.audit import AuditEvent, log_event
    log_event(AuditEvent.AUTH_FAILURE, ip="1.2.3.4", reason="invalid_key")
"""

import json
import logging
import time
from enum import StrEnum
from typing import Any

_audit_log = logging.getLogger("engramia.audit")


def resolve_actor(auth_ctx: Any) -> tuple[str | None, str | None]:
    """Split an :class:`AuthContext` into ``(actor_user_id, actor_key_id)``.

    Cloud-JWT auth packs the cloud user UUID into ``auth_ctx.key_id`` as
    ``cloud:USER_ID`` (see :mod:`engramia.api.auth`). Audit rows want the
    user UUID in its own typed column so the dashboard can distinguish
    cloud-auth callers from API-key callers cleanly.

    Returns a tuple where exactly one (or neither) is populated:

    - ``("USER_ID", None)`` for cloud-auth requests
    - ``(None, "KEY_UUID")`` for API-key auth
    - ``(None, None)`` when no auth context is present
    """
    if auth_ctx is None:
        return None, None
    kid = getattr(auth_ctx, "key_id", None)
    if not kid:
        return None, None
    if kid.startswith("cloud:"):
        return kid.split(":", 1)[1] or None, None
    return None, kid


class AuditEvent(StrEnum):
    AUTH_FAILURE = "auth_failure"
    AUTH_SUCCESS = "auth_success"
    PATTERN_DELETED = "pattern_deleted"
    RATE_LIMITED = "rate_limited"
    BULK_IMPORT = "bulk_import"
    KEY_CREATED = "key_created"
    KEY_REVOKED = "key_revoked"
    KEY_ROTATED = "key_rotated"
    QUOTA_EXCEEDED = "quota_exceeded"
    # Phase 5.6: Data Governance
    SCOPE_DELETED = "scope_deleted"
    SCOPE_EXPORTED = "scope_exported"
    RETENTION_APPLIED = "retention_applied"
    PII_REDACTED = "pii_redacted"
    DATA_EXPORTED = "data_exported"
    # Phase 6.5: Cloud onboarding (Variant A — manual admin)
    WAITLIST_SUBMITTED = "waitlist_submitted"
    WAITLIST_APPROVED = "waitlist_approved"
    WAITLIST_REJECTED = "waitlist_rejected"
    FIRST_PASSWORD_CHANGED = "first_password_changed"
    # Operator-driven account deletion via `engramia cloud delete-account`.
    # `mode` kwarg distinguishes "soft" (GDPR Art. 17 path, 30d grace via
    # cleanup deleted-accounts cron) from "hard" (immediate cascade DELETE,
    # ops/testing only).
    ACCOUNT_DELETED = "account_deleted"


def log_event(event: AuditEvent, **kwargs: Any) -> None:
    """Emit a structured audit log entry at WARNING level.

    The entry is serialized as JSON for machine-parseable audit trails.

    Args:
        event: The audit event type.
        **kwargs: Additional context fields (ip, path, reason, key_id, etc.).
    """
    entry = {
        "audit": True,
        "event": event.value,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **kwargs,
    }
    _audit_log.warning("AUDIT %s", json.dumps(entry, default=str))


def log_db_event(
    engine,
    *,
    tenant_id: str,
    project_id: str | None,
    action: str,
    key_id: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Write an audit event to the ``audit_log`` DB table.

    Failures are logged and silently swallowed — audit logging must never
    interrupt the main request flow.

    Args:
        engine: SQLAlchemy engine (from app.state.auth_engine).
        tenant_id: Tenant the event belongs to.
        project_id: Project the event belongs to. ``None`` for tenant-level
            events (e.g. account deletion) — column is nullable since
            migration 022.
        action: Event action string (e.g. 'key_created', 'key_revoked').
        key_id: UUID of the API key involved, if applicable.
        actor_user_id: UUID of the cloud user who initiated the request.
            Populated when auth was a cloud JWT (migration 031). Use
            :func:`resolve_actor` to split an :class:`AuthContext`.
        resource_type: Type of resource affected (e.g. 'api_key').
        resource_id: ID of the affected resource.
        ip_address: Client IP address.
        detail: Structured event context (diff, counts, reason). Stored as
            JSONB on PostgreSQL via ``CAST(:detail AS jsonb)``; serialised
            to text on SQLite (the SELECT path detects and parses it).
    """
    try:
        from sqlalchemy import text

        # JSONB roundtrip — match the project-wide pattern noted in
        # MEMORY.md ("CAST(:p AS jsonb)" + json.dumps; the ":p::jsonb"
        # form collides with SQLAlchemy's named-param parser). SQLite has
        # no JSONB so we fall back to plain TEXT and let the read path
        # parse via ``_parse_detail``.
        is_postgres = engine.dialect.name == "postgresql"
        detail_payload = json.dumps(detail) if detail else None

        if is_postgres:
            sql = (
                "INSERT INTO audit_log "
                "(tenant_id, project_id, key_id, actor_user_id, action, "
                " resource_type, resource_id, ip_address, detail, created_at) "
                "VALUES (:tid, :pid, :kid, :uid, :action, :rtype, :rid, :ip, "
                "        CAST(:detail AS jsonb), now()::text)"
            )
        else:
            sql = (
                "INSERT INTO audit_log "
                "(tenant_id, project_id, key_id, actor_user_id, action, "
                " resource_type, resource_id, ip_address, detail, created_at) "
                "VALUES (:tid, :pid, :kid, :uid, :action, :rtype, :rid, :ip, "
                "        :detail, now()::text)"
            )

        with engine.begin() as conn:
            conn.execute(
                text(sql),
                {
                    "tid": tenant_id,
                    "pid": project_id,
                    "kid": key_id,
                    "uid": actor_user_id,
                    "action": action,
                    "rtype": resource_type,
                    "rid": resource_id,
                    "ip": ip_address,
                    "detail": detail_payload,
                },
            )
    except Exception as exc:
        _audit_log.error("Failed to write DB audit event %r: %s", action, exc)
