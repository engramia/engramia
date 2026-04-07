# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CLI entry point for the audit-log PII scrubber.

Usage::

    python -m engramia.governance.scrub_audit_logs --older-than 90
    python -m engramia.governance.scrub_audit_logs --older-than 30 --dry-run

Environment variables
---------------------
ENGRAMIA_DATABASE_URL
    PostgreSQL connection string (required).

Exit codes
----------
0   Success (including dry-run with zero rows to scrub).
1   Fatal error (missing env var, DB connection failure, unexpected exception).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scrub_audit_logs",
        description=(
            "Scrub PII (e-mail, IP, name fields) from Engramia audit log entries "
            "older than N days. Keeps action, timestamp, resource_id, and all "
            "non-PII fields intact. Safe to run multiple times (idempotent)."
        ),
    )
    parser.add_argument(
        "--older-than",
        type=int,
        default=90,
        metavar="DAYS",
        help="Scrub records older than this many days (default: 90).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview: count affected rows but make no DB changes.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    log = logging.getLogger(__name__)

    db_url = os.environ.get("ENGRAMIA_DATABASE_URL", "").strip()
    if not db_url:
        log.error(
            "ENGRAMIA_DATABASE_URL is not set. "
            "Export it before running this script."
        )
        sys.exit(1)

    try:
        from sqlalchemy import create_engine

        engine = create_engine(db_url, pool_pre_ping=True)
    except Exception as exc:
        log.error("Failed to create DB engine: %s", exc)
        sys.exit(1)

    try:
        from engramia.governance.audit_scrubber import AuditScrubber

        scrubber = AuditScrubber(engine=engine)
        result = scrubber.scrub(older_than_days=args.older_than, dry_run=args.dry_run)
    except Exception as exc:
        log.error("Scrub failed: %s", exc, exc_info=True)
        sys.exit(1)

    verb = "Would scrub" if result.dry_run else "Scrubbed"
    log.info(
        "%s %d audit log row(s) older than %d days.",
        verb,
        result.rows_scrubbed,
        result.older_than_days,
    )
    if result.dry_run and result.rows_scrubbed > 0:
        log.info("Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
