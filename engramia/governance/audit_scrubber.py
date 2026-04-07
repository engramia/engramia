# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Audit log PII scrubber — GDPR Art. 5(1)(e) storage limitation.

Replaces personal data (e-mail, IP address, name fields) in ``audit_log``
entries older than N days with ``[REDACTED]`` while preserving all
security-relevant metadata (action, timestamp, resource_id, tenant_id,
project_id, key_id).

The operation is **idempotent**: rows that have already been fully scrubbed
produce no DB write on subsequent runs.

Usage (programmatic)::

    from engramia.governance.audit_scrubber import AuditScrubber

    scrubber = AuditScrubber(engine=engine)
    result = scrubber.scrub(older_than_days=90, dry_run=False)
    print(f"Scrubbed {result.rows_scrubbed} row(s).")

CLI::

    python -m engramia.governance.scrub_audit_logs --older-than 90
    python -m engramia.governance.scrub_audit_logs --older-than 30 --dry-run
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII detection patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# JSON keys whose values are unconditionally replaced with [REDACTED].
# String values for all other keys are still scanned with the regex patterns.
_PII_KEYS: frozenset[str] = frozenset(
    {
        "email",
        "user_email",
        "subject_email",
        "name",
        "full_name",
        "first_name",
        "last_name",
        "ip",
        "ip_address",
        "remote_addr",
        "client_ip",
    }
)

_REDACTED = "[REDACTED]"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ScrubResult:
    """Outcome of a single scrub run.

    Attributes:
        rows_scrubbed: Number of rows that were (or would be, in dry-run) modified.
        dry_run: Whether the run was a dry-run (no DB writes).
        older_than_days: Age threshold used for this run.
    """

    rows_scrubbed: int
    dry_run: bool
    older_than_days: int


# ---------------------------------------------------------------------------
# Value scrubbing helpers
# ---------------------------------------------------------------------------


def _scrub_value(value: object) -> object:
    """Recursively scrub PII from a JSON-serialisable value.

    - ``dict``: values whose key is in ``_PII_KEYS`` are replaced wholesale;
      other values are recursed into.
    - ``list``: each element is recursed into.
    - ``str``: e-mail and IP patterns are replaced with ``[REDACTED]``.
    - All other types are returned unchanged.
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k in _PII_KEYS else _scrub_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, str):
        value = _EMAIL_RE.sub(_REDACTED, value)
        value = _IP_RE.sub(_REDACTED, value)
        return value
    return value


# ---------------------------------------------------------------------------
# AuditScrubber
# ---------------------------------------------------------------------------


class AuditScrubber:
    """Scrubs PII from ``audit_log`` entries older than N days.

    Args:
        engine: Synchronous SQLAlchemy engine pointing at the Engramia DB.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrub(self, older_than_days: int = 90, dry_run: bool = False) -> ScrubResult:
        """Scrub PII from audit records older than ``older_than_days`` days.

        For each qualifying row:

        * ``ip_address`` is replaced with ``[REDACTED]`` (if not already).
        * ``detail`` (JSONB) is recursively scrubbed using :func:`_scrub_value`.

        Rows where neither field needs changing are skipped, making the
        operation **idempotent** — safe to run multiple times.

        Args:
            older_than_days: Age threshold in days. Only rows with
                ``created_at < now() - older_than_days`` are eligible.
            dry_run: When ``True``, compute the count but make no DB writes.

        Returns:
            :class:`ScrubResult` describing the outcome.
        """
        from sqlalchemy import text

        cutoff = (
            datetime.datetime.now(tz=datetime.UTC)
            - datetime.timedelta(days=older_than_days)
        ).isoformat()

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, ip_address, detail "
                    "FROM audit_log "
                    "WHERE created_at < :cutoff"
                ),
                {"cutoff": cutoff},
            ).fetchall()

        rows_scrubbed = 0

        for row in rows:
            row_id = row[0]
            ip_address = row[1]
            detail = row[2]  # Python dict (psycopg2 auto-deserialises JSONB) or None

            new_ip = _REDACTED if (ip_address and ip_address != _REDACTED) else ip_address
            new_detail = _scrub_value(detail) if detail is not None else None

            ip_changed = new_ip != ip_address
            detail_changed = detail is not None and new_detail != detail

            if not ip_changed and not detail_changed:
                continue

            rows_scrubbed += 1

            if dry_run:
                continue

            self._apply_update(row_id, new_ip, new_detail if detail_changed else detail)

        _log.info(
            "AuditScrubber: %s %d row(s) older than %d days.",
            "would scrub" if dry_run else "scrubbed",
            rows_scrubbed,
            older_than_days,
        )
        return ScrubResult(
            rows_scrubbed=rows_scrubbed,
            dry_run=dry_run,
            older_than_days=older_than_days,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_update(self, row_id: int, new_ip: str | None, new_detail: object) -> None:
        from sqlalchemy import text

        detail_json = json.dumps(new_detail) if new_detail is not None else None

        if detail_json is not None:
            sql = (
                "UPDATE audit_log "
                "SET ip_address = :ip, detail = CAST(:detail AS jsonb) "
                "WHERE id = :id"
            )
            params: dict = {"ip": new_ip, "detail": detail_json, "id": row_id}
        else:
            sql = "UPDATE audit_log SET ip_address = :ip WHERE id = :id"
            params = {"ip": new_ip, "id": row_id}

        with self._engine.begin() as conn:
            conn.execute(text(sql), params)
