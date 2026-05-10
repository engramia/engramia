# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Admin audit log writer.

Two-step pattern that survives mid-action crashes:

  1. ``log_admin_event(..., status='attempted')`` returns an ``id``.
  2. Action runs.
  3. ``update_admin_event_status(id, 'succeeded' | 'failed', ...)``.

A row stuck in ``attempted`` therefore signals an action that started
but never completed — exactly the forensic trail we want.

JSONB write goes through ``CAST(:detail AS jsonb)`` per the project-wide
SQLAlchemy pattern (see ``engramia.api.audit:144`` and
``MEMORY.md feedback_sqlalchemy_jsonb``). SQLite falls back to TEXT.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

_log = logging.getLogger(__name__)

AdminAuditStatus = Literal["attempted", "succeeded", "failed"]

_SENSITIVE_KEYS = frozenset({
    "password", "totp_code", "code", "totp", "authorization",
    "refresh_token", "intermediate_token", "x-admin-token",
})


def _redact(payload: Any) -> Any:
    """Walk *payload* and mask any value whose key looks sensitive."""
    if isinstance(payload, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _SENSITIVE_KEYS else _redact(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_redact(x) for x in payload]
    return payload


def log_admin_event(
    engine: Engine,
    *,
    actor_admin_user_id: int,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    target_tenant_id: int | None = None,
    environment: str,
    ip_address: str,
    detail: dict | None = None,
) -> int:
    """Insert an ``attempted`` row and return its primary key.

    *environment* should be ``'staging'`` or ``'prod'`` — the value is
    written verbatim and used for forensic queries that need to scope by
    target Core deployment.
    """
    is_postgres = engine.dialect.name == "postgresql"
    detail_payload = json.dumps(_redact(detail)) if detail else None

    if is_postgres:
        sql = (
            "INSERT INTO admin_audit_log "
            "(actor_admin_user_id, action, resource_type, resource_id, "
            " target_tenant_id, status, environment, ip_address, detail) "
            "VALUES (:uid, :action, :rtype, :rid, :tid, 'attempted', "
            "        :env, :ip, CAST(:detail AS jsonb)) RETURNING id"
        )
    else:
        sql = (
            "INSERT INTO admin_audit_log "
            "(actor_admin_user_id, action, resource_type, resource_id, "
            " target_tenant_id, status, environment, ip_address, detail) "
            "VALUES (:uid, :action, :rtype, :rid, :tid, 'attempted', "
            "        :env, :ip, :detail) RETURNING id"
        )

    with engine.begin() as conn:
        row = conn.execute(
            text(sql),
            {
                "uid": actor_admin_user_id,
                "action": action,
                "rtype": resource_type,
                "rid": resource_id,
                "tid": target_tenant_id,
                "env": environment,
                "ip": ip_address,
                "detail": detail_payload,
            },
        ).first()
    if row is None:
        raise RuntimeError("admin_audit_log INSERT did not return an id")
    return int(row[0])


def update_admin_event_status(
    engine: Engine,
    *,
    event_id: int,
    status: AdminAuditStatus,
    error: str | None = None,
    result_detail: dict | None = None,
) -> None:
    """Transition a row from ``attempted`` to ``succeeded`` or ``failed``.

    Existing ``detail`` is merged with the result/error. The merge is
    intentionally simple — string-concat at the JSON level via a CTE
    would be overkill given how rarely admin actions occur. We re-read
    the existing detail, merge in Python, and write back.
    """
    if status == "attempted":
        raise ValueError("update_admin_event_status: status must be 'succeeded' or 'failed'")

    with engine.begin() as conn:
        existing_row = conn.execute(
            text("SELECT detail FROM admin_audit_log WHERE id = :id"),
            {"id": event_id},
        ).first()
        if existing_row is None:
            _log.error("update_admin_event_status: id=%s not found", event_id)
            return
        existing_detail = existing_row[0]
        if isinstance(existing_detail, str):
            try:
                existing_detail = json.loads(existing_detail)
            except json.JSONDecodeError:
                existing_detail = {"raw": existing_detail}
        elif existing_detail is None:
            existing_detail = {}

        merged = dict(existing_detail)
        if result_detail:
            merged["result"] = _redact(result_detail)
        if error:
            merged["error"] = error
        merged_json = json.dumps(merged) if merged else None

        is_postgres = engine.dialect.name == "postgresql"
        if is_postgres:
            update_sql = (
                "UPDATE admin_audit_log SET status = :status, "
                "completed_at = :ts, detail = CAST(:detail AS jsonb) "
                "WHERE id = :id"
            )
        else:
            update_sql = (
                "UPDATE admin_audit_log SET status = :status, "
                "completed_at = :ts, detail = :detail WHERE id = :id"
            )

        conn.execute(
            text(update_sql),
            {
                "status": status,
                "ts": datetime.now(UTC),
                "detail": merged_json,
                "id": event_id,
            },
        )
