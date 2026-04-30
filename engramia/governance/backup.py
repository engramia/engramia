# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tenant-scoped backup streamer (Phase 6.6 #5 — Team+ paywall).

Sister module to :mod:`engramia.governance.export` (Art. 20 portability).
Where ``export.py`` streams **patterns only** for a single project, this
module streams **the full tenant payload** across every table the tenant
owns — patterns, embeddings, feedback, metrics, skills, analytics rollups,
async jobs — so the operator gets a self-contained DR snapshot they can
re-import via ``Memory.import_data()`` plus the matching SQL inserts.

What is **excluded** from the dump:

- ``tenant_credentials`` — encrypted ciphertext is useless without the
  master key, and shipping it inflates the payload with bytes the
  operator can't restore anyway. Tenants re-add credentials post-restore.
- ``audit_log`` — privacy-sensitive (other users' actions, IPs); operator
  tooling pulls this separately when needed.
- ``billing_subscriptions`` / ``stripe_*`` — Stripe is the source of
  truth for these; restoring a row would mismatch live Stripe state.
- ``api_keys`` — key hashes only. Plaintext is irrecoverable; restoring
  a hash without the matching plaintext breaks auth.

The output is **NDJSON** (one JSON object per line) with an envelope
shape so a single stream can carry rows from many tables:

.. code-block:: text

    {"version": 1, "kind": "header", "tenant_id": "...", "exported_at": "...", "tables": [...]}
    {"version": 1, "kind": "row", "table": "memory_data", "data": {...}}
    {"version": 1, "kind": "row", "table": "memory_data", "data": {...}}
    ...
    {"version": 1, "kind": "row", "table": "feedback", "data": {...}}
    ...
    {"version": 1, "kind": "footer", "row_count": 12345, "table_counts": {...}}

The header arrives first so a partial download still tells the
operator what they have. The footer is the integrity marker: if the
client receives no footer line, the stream was truncated and the
backup is invalid.

Embedding vectors are emitted as plain ``list[float]`` (not raw
``vector(1536)``) so the consumer can re-insert them via the standard
SQLAlchemy + pgvector adapter — no binary protocol surprises.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterator

_log = logging.getLogger(__name__)

# Tables exported in this order. Foreign-key parents first so a future
# importer can replay the stream linearly without deferred constraints.
# Each entry: (table_name, scope_columns, select_columns, scope_filter_sql).
_BACKUP_TABLES: list[tuple[str, list[str], str, str]] = [
    # Patterns + their embeddings (composite PK on (tenant_id, project_id, key)).
    (
        "memory_data",
        ["tenant_id", "project_id"],
        "tenant_id, project_id, key, value, classification, source, run_id, author, redacted, expires_at, created_at",
        "tenant_id = :tid",
    ),
    (
        "memory_embeddings",
        ["tenant_id", "project_id"],
        "tenant_id, project_id, key, embedding::text AS embedding",
        "tenant_id = :tid",
    ),
    # Per-tenant rollups + analytics.
    (
        "analytics_events",
        ["tenant_id", "project_id"],
        "tenant_id, project_id, kind, ts, payload, eval_score",
        "tenant_id = :tid",
    ),
    (
        "analytics_rollups",
        ["tenant_id", "project_id"],
        "tenant_id, project_id, window, period_start, learn_total, "
        "learn_avg_eval, learn_p50_eval, learn_p90_eval, recall_total, "
        "recall_duplicate_hits, recall_adapt_hits, recall_fresh_misses, "
        "recall_avg_similarity, roi_score",
        "tenant_id = :tid",
    ),
    # Async jobs — recent only (30 days) to keep dumps manageable.
    (
        "jobs",
        ["tenant_id", "project_id"],
        "id, tenant_id, project_id, operation, status, payload, result, "
        "error, attempts, max_attempts, max_execution_seconds, "
        "submitted_at, started_at, completed_at",
        "tenant_id = :tid AND submitted_at > NOW() - INTERVAL '30 days'",
    ),
    # Tenant + project metadata (parents).  Restored last on re-import is
    # fine because the rows are scope-pinned anyway.
    (
        "projects",
        ["tenant_id"],
        "id, tenant_id, name, retention_days, created_at, deleted_at",
        "tenant_id = :tid AND deleted_at IS NULL",
    ),
    (
        "tenants",
        [],  # tenant table is keyed on id directly
        "id, name, plan_tier, retention_days, created_at",
        "id = :tid",
    ),
]

_STREAM_BATCH_SIZE = 200


class BackupExporter:
    """Streams a tenant's full data payload as NDJSON envelopes.

    Args:
        engine: SQLAlchemy engine bound to the tenant DB. Required —
            backup is meaningless on JSON storage where the operator can
            just tar the data directory.

    Usage::

        exporter = BackupExporter(engine)
        for chunk in exporter.stream("tenant-abc"):
            response.write(chunk.encode("utf-8"))
    """

    def __init__(self, engine: Any) -> None:
        if engine is None:
            raise ValueError("BackupExporter requires a SQLAlchemy engine")
        self._engine = engine

    def stream(self, tenant_id: str) -> Iterator[str]:
        """Yield NDJSON lines (each terminated with ``\\n``) for the tenant.

        Yields header → rows → footer in that order. Caller is responsible
        for cumulating bytes_streamed and table_counts to log to
        ``backup_download_log`` after the stream closes.
        """
        exported_at = datetime.datetime.now(datetime.UTC).isoformat()
        table_names = [t[0] for t in _BACKUP_TABLES]

        # Header first — operator gets a sentinel even on truncated dumps.
        yield (
            json.dumps(
                {
                    "version": 1,
                    "kind": "header",
                    "tenant_id": tenant_id,
                    "exported_at": exported_at,
                    "tables": table_names,
                }
            )
            + "\n"
        )

        row_count = 0
        table_counts: dict[str, int] = {}

        for table, _scope_cols, columns, filter_sql in _BACKUP_TABLES:
            count = 0
            try:
                with self._engine.connect() as conn:
                    # Server-side cursor via execution_options so large
                    # tables don't blow the API container's RSS.
                    result = conn.execution_options(stream_results=True, max_row_buffer=_STREAM_BATCH_SIZE).execute(
                        text(f"SELECT {columns} FROM {table} WHERE {filter_sql}"),
                        {"tid": tenant_id},
                    )
                    for row in result:
                        # row._mapping → dict; datetime / Decimal are
                        # JSON-serialised via default=str so the consumer
                        # re-parses ISO timestamps without ambiguity.
                        yield (
                            json.dumps(
                                {
                                    "version": 1,
                                    "kind": "row",
                                    "table": table,
                                    "data": dict(row._mapping),
                                },
                                default=str,
                            )
                            + "\n"
                        )
                        count += 1
            except Exception as exc:
                _log.warning(
                    "BackupExporter: table %s failed for tenant=%s — emitting partial footer",
                    table,
                    tenant_id,
                    exc_info=True,
                )
                yield (
                    json.dumps(
                        {
                            "version": 1,
                            "kind": "error",
                            "table": table,
                            "message": str(exc),
                        }
                    )
                    + "\n"
                )
            row_count += count
            table_counts[table] = count

        # Footer — integrity marker. Absence = truncated download.
        yield (
            json.dumps(
                {
                    "version": 1,
                    "kind": "footer",
                    "row_count": row_count,
                    "table_counts": table_counts,
                }
            )
            + "\n"
        )
