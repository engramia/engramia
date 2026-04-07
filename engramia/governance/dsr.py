# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Data Subject Request (DSR) tracking — GDPR Art. 15-20.

Provides a lightweight queue and status tracker for Data Subject Requests
so that operators can demonstrate GDPR compliance with measurable SLAs.

Supported request types
-----------------------
- ``access``        Art. 15 — subject wants a copy of their data
- ``erasure``       Art. 17 — "right to be forgotten"
- ``portability``   Art. 20 — machine-readable data export
- ``rectification`` Art. 16 — correct inaccurate personal data

SLA
---
Default SLA is 30 days (GDPR Art. 12 §3).  A separate ``ENGRAMIA_DSR_SLA_DAYS``
env var allows operators to tighten it.  Requests past their deadline are
returned with ``overdue=True`` so monitoring dashboards can alert.

Near-deadline warnings
----------------------
Any open request within 7 days of its ``due_at`` deadline emits a WARNING-level
log message so that Loki/Grafana alert rules can pick it up.

Storage
-------
DSRs are stored in the ``data_subject_requests`` table (migration 010).
When no DB engine is available (JSON storage mode) requests are stored
in-memory for the lifetime of the process and a warning is emitted.
"""

from __future__ import annotations

import datetime
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Literal

_log = logging.getLogger(__name__)

DSRType = Literal["access", "erasure", "portability", "rectification"]
DSRStatus = Literal["pending", "in_progress", "completed", "rejected"]

_SLA_DAYS = int(os.environ.get("ENGRAMIA_DSR_SLA_DAYS", "30"))
_DEADLINE_WARN_DAYS = 7  # Warn when fewer than this many days remain

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


@dataclass
class DSRRequest:
    """A single Data Subject Request record.

    Args:
        id: UUID string (auto-generated).
        tenant_id: Tenant that received the request.
        request_type: Type of DSR (access / erasure / portability / rectification).
        subject_email: E-mail address of the data subject.
        status: Current processing status.
        created_at: ISO-8601 UTC timestamp when the request was created.
        due_at: ISO-8601 UTC timestamp of the SLA deadline (created_at + SLA).
        updated_at: ISO-8601 UTC timestamp of the last status change.
        completed_at: ISO-8601 UTC timestamp when the request was fulfilled.
        handler_notes: Free-text notes for the operator.
        overdue: True when status != "completed" / "rejected" and deadline has passed.
    """

    id: str
    tenant_id: str
    request_type: DSRType
    subject_email: str
    status: DSRStatus
    created_at: str
    due_at: str
    updated_at: str
    completed_at: str | None = None
    handler_notes: str = ""

    @property
    def overdue(self) -> bool:
        if self.status in ("completed", "rejected"):
            return False
        try:
            due_dt = datetime.datetime.fromisoformat(self.due_at)
            return datetime.datetime.now(tz=datetime.UTC) > due_dt
        except ValueError:
            return False

    @property
    def days_until_due(self) -> float | None:
        """Return days remaining until the SLA deadline, or None on parse error."""
        try:
            due_dt = datetime.datetime.fromisoformat(self.due_at)
            delta = due_dt - datetime.datetime.now(tz=datetime.UTC)
            return delta.total_seconds() / 86400
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# In-memory fallback store (dev / JSON storage mode)
# ---------------------------------------------------------------------------

_mem_store: dict[str, DSRRequest] = {}


# ---------------------------------------------------------------------------
# DSRTracker
# ---------------------------------------------------------------------------


class DSRTracker:
    """Queue and status tracker for Data Subject Requests.

    Args:
        engine: SQLAlchemy engine. ``None`` → in-memory mode (dev only).
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine
        if engine is None:
            _log.warning(
                "DSRTracker: no DB engine — using in-memory store. "
                "DSRs will be lost on process restart. Use PostgreSQL for production."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        tenant_id: str,
        request_type: DSRType,
        subject_email: str,
        handler_notes: str = "",
    ) -> DSRRequest:
        """Create a new DSR and persist it.

        Args:
            tenant_id: Tenant receiving the request.
            request_type: Type of DSR.
            subject_email: E-mail of the data subject.
            handler_notes: Optional operator notes.

        Returns:
            The created :class:`DSRRequest`.
        """
        now = datetime.datetime.now(tz=datetime.UTC)
        due_at = now + datetime.timedelta(days=_SLA_DAYS)
        req = DSRRequest(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            request_type=request_type,
            subject_email=subject_email,
            status="pending",
            created_at=now.isoformat(),
            due_at=due_at.isoformat(),
            updated_at=now.isoformat(),
            handler_notes=handler_notes,
        )
        self._persist(req)
        _log.info(
            "DSR created: id=%s type=%s tenant=%s due_at=%s",
            req.id,
            req.request_type,
            req.tenant_id,
            req.due_at[:10],
        )
        self._maybe_warn_deadline(req)
        return req

    def update_status(
        self,
        dsr_id: str,
        status: DSRStatus,
        handler_notes: str = "",
    ) -> DSRRequest | None:
        """Update the status of an existing DSR.

        Args:
            dsr_id: UUID of the DSR.
            status: New status.
            handler_notes: Optional operator notes to append.

        Returns:
            Updated :class:`DSRRequest`, or ``None`` if not found.
        """
        req = self.get(dsr_id)
        if req is None:
            return None
        now = datetime.datetime.now(tz=datetime.UTC)
        req.status = status
        req.updated_at = now.isoformat()
        if handler_notes:
            req.handler_notes = f"{req.handler_notes}\n{handler_notes}".strip()
        if status in ("completed", "rejected"):
            req.completed_at = now.isoformat()
        self._persist(req)
        _log.info("DSR updated: id=%s status=%s", req.id, status)
        self._maybe_warn_deadline(req)
        return req

    def get(self, dsr_id: str) -> DSRRequest | None:
        """Return a single DSR by ID, or ``None`` if not found."""
        if self._engine is None:
            return _mem_store.get(dsr_id)
        return self._db_get(dsr_id)

    def list_requests(
        self,
        tenant_id: str,
        status: DSRStatus | None = None,
        overdue_only: bool = False,
        limit: int = 100,
    ) -> list[DSRRequest]:
        """List DSRs for a tenant with optional filters.

        Emits WARNING-level log messages for any open requests within
        ``_DEADLINE_WARN_DAYS`` days of their SLA deadline.

        Args:
            tenant_id: Tenant to query.
            status: Filter by status (``None`` = all).
            overdue_only: When True, return only past-deadline open requests.
            limit: Maximum number of results.

        Returns:
            List of :class:`DSRRequest` sorted by ``created_at`` descending.
        """
        if self._engine is None:
            requests = [r for r in _mem_store.values() if r.tenant_id == tenant_id]
        else:
            requests = self._db_list(tenant_id, status, limit)

        if status is not None:
            requests = [r for r in requests if r.status == status]
        if overdue_only:
            requests = [r for r in requests if r.overdue]
        requests.sort(key=lambda r: r.created_at, reverse=True)
        result = requests[:limit]

        for req in result:
            self._maybe_warn_deadline(req)

        return result

    def pending_count(self, tenant_id: str) -> dict[str, int]:
        """Return counts of open DSRs grouped by status for a tenant.

        Returns a dict: ``{"pending": N, "in_progress": N, "overdue": N}``.
        """
        requests = self.list_requests(tenant_id)
        open_reqs = [r for r in requests if r.status not in ("completed", "rejected")]
        return {
            "pending": sum(1 for r in open_reqs if r.status == "pending"),
            "in_progress": sum(1 for r in open_reqs if r.status == "in_progress"),
            "overdue": sum(1 for r in open_reqs if r.overdue),
        }

    # ------------------------------------------------------------------
    # Near-deadline warning
    # ------------------------------------------------------------------

    @staticmethod
    def _maybe_warn_deadline(req: DSRRequest) -> None:
        """Emit a WARNING log if the request is open and within 7 days of due_at."""
        if req.status in ("completed", "rejected"):
            return
        days = req.days_until_due
        if days is None:
            return
        if days < 0:
            _log.warning(
                "DSR overdue: id=%s type=%s tenant=%s due_at=%s overdue_by=%.1fd",
                req.id,
                req.request_type,
                req.tenant_id,
                req.due_at[:10],
                abs(days),
            )
        elif days <= _DEADLINE_WARN_DAYS:
            _log.warning(
                "DSR deadline approaching: id=%s type=%s tenant=%s due_at=%s days_remaining=%.1f",
                req.id,
                req.request_type,
                req.tenant_id,
                req.due_at[:10],
                days,
            )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist(self, req: DSRRequest) -> None:
        if self._engine is None:
            _mem_store[req.id] = req
            return
        self._db_upsert(req)

    def _db_upsert(self, req: DSRRequest) -> None:
        from sqlalchemy import text

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO data_subject_requests "
                        "(id, tenant_id, request_type, subject_email, status, "
                        " created_at, due_at, updated_at, completed_at, handler_notes) "
                        "VALUES (:id, :tenant_id, :request_type, :subject_email, :status, "
                        " :created_at, :due_at, :updated_at, :completed_at, :handler_notes) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "  status = :status, "
                        "  updated_at = :updated_at, "
                        "  completed_at = :completed_at, "
                        "  handler_notes = :handler_notes"
                    ),
                    {
                        "id": req.id,
                        "tenant_id": req.tenant_id,
                        "request_type": req.request_type,
                        "subject_email": req.subject_email,
                        "status": req.status,
                        "created_at": req.created_at,
                        "due_at": req.due_at,
                        "updated_at": req.updated_at,
                        "completed_at": req.completed_at,
                        "handler_notes": req.handler_notes,
                    },
                )
        except Exception as exc:
            _log.error("DSRTracker._db_upsert failed for id=%s: %s", req.id, exc, exc_info=True)
            raise

    def _db_get(self, dsr_id: str) -> DSRRequest | None:
        from sqlalchemy import text

        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT id, tenant_id, request_type, subject_email, status, "
                        "       created_at, due_at, updated_at, completed_at, handler_notes "
                        "FROM data_subject_requests WHERE id = :id"
                    ),
                    {"id": dsr_id},
                ).fetchone()
        except Exception as exc:
            _log.error("DSRTracker._db_get failed for id=%s: %s", dsr_id, exc, exc_info=True)
            return None
        if row is None:
            return None
        return self._row_to_dsr(row)

    def _db_list(self, tenant_id: str, status: DSRStatus | None, limit: int) -> list[DSRRequest]:
        from sqlalchemy import text

        filters = "WHERE tenant_id = :tenant_id"
        params: dict = {"tenant_id": tenant_id, "limit": limit}
        if status:
            filters += " AND status = :status"
            params["status"] = status

        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, tenant_id, request_type, subject_email, status, "
                        "       created_at, due_at, updated_at, completed_at, handler_notes "
                        f"FROM data_subject_requests {filters} "
                        "ORDER BY created_at DESC LIMIT :limit"
                    ),
                    params,
                ).fetchall()
        except Exception as exc:
            _log.error("DSRTracker._db_list failed: %s", exc, exc_info=True)
            return []
        return [self._row_to_dsr(row) for row in rows]

    @staticmethod
    def _row_to_dsr(row) -> DSRRequest:
        return DSRRequest(
            id=str(row[0]),
            tenant_id=str(row[1]),
            request_type=row[2],
            subject_email=str(row[3]),
            status=row[4],
            created_at=str(row[5]),
            due_at=str(row[6]),
            updated_at=str(row[7]),
            completed_at=str(row[8]) if row[8] else None,
            handler_notes=str(row[9]) if row[9] else "",
        )
