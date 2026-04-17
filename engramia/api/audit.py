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


class AuditEvent(StrEnum):
    AUTH_FAILURE = "auth_failure"
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
    project_id: str,
    action: str,
    key_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Write an audit event to the ``audit_log`` DB table.

    Called from key management routes where the tenant/project context is
    available. Failures are logged and silently swallowed — audit logging
    must never interrupt the main request flow.

    Args:
        engine: SQLAlchemy engine (from app.state.auth_engine).
        tenant_id: Tenant the event belongs to.
        project_id: Project the event belongs to.
        action: Event action string (e.g. 'key_created', 'key_revoked').
        key_id: UUID of the API key involved, if applicable.
        resource_type: Type of resource affected (e.g. 'api_key').
        resource_id: ID of the affected resource.
        ip_address: Client IP address.
    """
    try:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_log "
                    "(tenant_id, project_id, key_id, action, resource_type, resource_id, ip_address, created_at) "
                    "VALUES (:tid, :pid, :kid, :action, :rtype, :rid, :ip, now()::text)"
                ),
                {
                    "tid": tenant_id,
                    "pid": project_id,
                    "kid": key_id,
                    "action": action,
                    "rtype": resource_type,
                    "rid": resource_id,
                    "ip": ip_address,
                },
            )
    except Exception as exc:
        _audit_log.error("Failed to write DB audit event %r: %s", action, exc)
