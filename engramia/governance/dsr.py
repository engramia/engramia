# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Data Subject Request (DSR) tracking — GDPR Art. 15-20.

Provides a lightweight queue and status tracker for Data Subject Requests
so that operators can demonstrate GDPR compliance with measurable SLAs.

Supported request types
-----------------------
- ``access``      Art. 15 — subject wants a copy of their data
- ``erasure``     Art. 17 — "right to be forgotten"
- ``portability`` Art. 20 — machine-readable data export
- ``rectification`` Art. 16 — correct inaccurate personal data

SLA
---
Default SLA is 30 days (GDPR Art. 12 §3).  A separate ``ENGRAMIA_DSR_SLA_DAYS``
env var allows operators to tighten it.  Requests past their deadline are
returned with ``overdue=True`` so monitoring dashboards can alert.

Storage
-------
DSRs are stored in a dedicated table ``dsr_requests`` (migration 010).
When no DB engine is available (JSON storage mode) requests are stored
in-memory for the lifetime of the process and a warning is emitted.
"""

from __future__ import annotations

import datetime
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Literal

_log = logging.getLogger(__name__)

DSRType = Literal["access", "erasure", "portability", "rectification"]
DSRStatus = Literal["pending", "in_progress", "completed", "rejected"]

_SLA_DAYS = int(os.environ.get("ENGRAMIA_DSR_SLA_DAYS", "30"))

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
        deadline: ISO-8601 UTC timestamp of the SLA deadline (created_at + SLA).
        updated_at: ISO-8601 UTC timestamp of the last status change.
        completed_at: ISO-8601 UTC timestamp when the request was fulfilled.
        notes: Free-text notes for the operator.
        overdue: True when status != "completed" / "rejected" and deadline has passed.
    """

    id: str
    tenant_id: str
    request_type: DSRType
    subject_email: str
    status: DSRStatus
    created_at: str
    deadline: str
    updated_at: str
    completed_at: str | None = None
    notes: str = ""

    @property
    def overdue(self) -> bool:
        if self.status in ("completed", "rejected"):
            return False
        try:
            deadline_dt = datetime.datetime.fromisoformat(self.deadline)
            return datetime.datetime.now(tz=datetime.UTC) > deadline_dt
        except ValueError:
            return False


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
        notes: str = "",
    ) -> DSRRequest:
        """Create a new DSR and persist it.

        Args:
            tenant_id: Tenant receiving the request.
            request_type: Type of DSR.
            subject_email: E-mail of the data subject.
            notes: Optional operator notes.

        Returns:
            The created :class:`DSRRequest`.
        """
        now = datetime.datetime.now(tz=datetime.UTC)
        deadline = now + datetime.timedelta(days=_SLA_DAYS)
        req = DSRRequest(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            request_type=request_type,
            subject_email=subject_email,
            status="pending",
            created_at=now.isoformat(),
            deadline=deadline.isoformat(),
            updated_at=now.isoformat(),
            notes=notes,
        )
        self._persist(req)
        _log.info(
            "DSR created: id=%s type=%s tenant=%s deadline=%s",
            req.id,
            req.request_type,
            req.tenant_id,
            req.deadline[:10],
        )
        return req

    def update_status(
        self,
        dsr_id: str,
        status: DSRStatus,
        notes: str = "",
    ) -> DSRRequest | None:
        """Update the status of an existing DSR.

        Args:
            dsr_id: UUID of the DSR.
            status: New status.
            notes: Optional operator notes to append.

        Returns:
            Updated :class:`DSRRequest`, or ``None`` if not found.
        """
        req = self.get(dsr_id)
        if req is None:
            return None
        now = datetime.datetime.now(tz=datetime.UTC)
        req.status = status
        req.updated_at = now.isoformat()
        if notes:
            req.notes = f"{req.notes}\n{notes}".strip()
        if status in ("completed", "rejected"):
            req.completed_at = now.isoformat()
        self._persist(req)
        _log.info("DSR updated: id=%s status=%s", req.id, status)
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
        return requests[:limit]

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
                        "INSERT INTO dsr_requests "
                        "(id, tenant_id, request_type, subject_email, status, "
                        " created_at, deadline, updated_at, completed_at, notes) "
                        "VALUES (:id, :tenant_id, :request_type, :subject_email, :status, "
                        " :created_at, :deadline, :updated_at, :completed_at, :notes) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "  status = :status, "
                        "  updated_at = :updated_at, "
                        "  completed_at = :completed_at, "
                        "  notes = :notes"
                    ),
                    {
                        "id": req.id,
                        "tenant_id": req.tenant_id,
                        "request_type": req.request_type,
                        "subject_email": req.subject_email,
                        "status": req.status,
                        "created_at": req.created_at,
                        "deadline": req.deadline,
                        "updated_at": req.updated_at,
                        "completed_at": req.completed_at,
                        "notes": req.notes,
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
                        "       created_at, deadline, updated_at, completed_at, notes "
                        "FROM dsr_requests WHERE id = :id"
                    ),
                    {"id": dsr_id},
                ).fetchone()
        except Exception as exc:
            _log.error("DSRTracker._db_get failed for id=%s: %s", dsr_id, exc, exc_info=True)
            return None
        if row is None:
            return None
        return self._row_to_dsr(row)

    def _db_list(
        self, tenant_id: str, status: DSRStatus | None, limit: int
    ) -> list[DSRRequest]:
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
                        "       created_at, deadline, updated_at, completed_at, notes "
                        f"FROM dsr_requests {filters} "
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
            deadline=str(row[6]),
            updated_at=str(row[7]),
            completed_at=str(row[8]) if row[8] else None,
            notes=str(row[9]) if row[9] else "",
        )
