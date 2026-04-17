# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Scoped data export — GDPR Art. 20 data portability (Phase 5.6).

Streams all patterns for the current scope as a sequence of dicts
(NDJSON-compatible). Optional classification filter limits what is exported.

Usage::

    exporter = DataExporter()
    for record in exporter.stream(storage, classification_filter=["public", "internal"]):
        ndjson_file.write(json.dumps(record) + "\\n")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Iterator

from engramia._util import PATTERNS_PREFIX

_log = logging.getLogger(__name__)

# Batch size for streaming (avoids loading all data into memory)
_STREAM_BATCH_SIZE = 100


class DataExporter:
    """Streams patterns from the current scope as portable records.

    Records have a stable format suitable for re-import via ``Memory.import_data()``:

    .. code-block:: json

        {
            "version": 1,
            "key": "patterns/abc123_1234567890",
            "data": { "task": "...", "design": {...}, ... },
            "classification": "internal",
            "redacted": false
        }

    The ``classification`` and ``redacted`` fields come from the DB columns
    when PostgreSQL storage is used; otherwise they default to ``"internal"``
    and ``false``.
    """

    def stream(
        self,
        storage,
        classification_filter: list[str] | None = None,
        engine=None,
    ) -> Iterator[dict[str, Any]]:
        """Stream all patterns for the current scope.

        Args:
            storage: StorageBackend (scoped to current tenant/project).
            classification_filter: If set, only export patterns whose
                classification is in this list (e.g. ``["public", "internal"]``).
                None exports all classifications.
            engine: SQLAlchemy engine for reading DB governance columns.
                Optional — if None, classification metadata is omitted.

        Yields:
            One dict per pattern.
        """
        meta_by_key: dict[str, dict[str, Any]] = {}
        if engine is not None:
            meta_by_key = self._load_meta_from_db(engine, storage, classification_filter)

        keys = storage.list_keys(prefix=PATTERNS_PREFIX)

        for key in keys:
            # Apply classification filter when DB metadata is available
            if classification_filter is not None and engine is not None:
                meta = meta_by_key.get(key)
                if meta is None:
                    continue  # Not in filtered result set
            else:
                meta = meta_by_key.get(key, {})

            data = storage.load(key)
            if data is None:
                continue

            record: dict[str, Any] = {
                "version": 1,
                "key": key,
                "data": data,
            }
            if meta:
                record["classification"] = meta.get("classification", "internal")
                record["redacted"] = meta.get("redacted", False)
                if meta.get("source"):
                    record["source"] = meta["source"]
                if meta.get("run_id"):
                    record["run_id"] = meta["run_id"]

            yield record

    def _load_meta_from_db(
        self,
        engine,
        storage,
        classification_filter: list[str] | None,
    ) -> dict[str, dict[str, Any]]:
        """Load governance metadata from memory_data columns."""
        from engramia._context import get_scope

        scope = get_scope()
        try:
            query = (
                "SELECT key, classification, redacted, source, run_id "
                "FROM memory_data "
                "WHERE tenant_id = :tid AND project_id = :pid AND key LIKE :prefix"
            )
            params: dict[str, Any] = {
                "tid": scope.tenant_id,
                "pid": scope.project_id,
                "prefix": f"{PATTERNS_PREFIX}/%",
            }

            if classification_filter:
                # Use positional placeholders for the IN clause
                placeholders = ", ".join(f":cls{i}" for i in range(len(classification_filter)))
                query += f" AND classification IN ({placeholders})"
                for i, cls in enumerate(classification_filter):
                    params[f"cls{i}"] = cls

            with engine.connect() as conn:
                rows = conn.execute(text(query), params).fetchall()

            return {
                row.key: {
                    "classification": row.classification,
                    "redacted": row.redacted,
                    "source": row.source,
                    "run_id": row.run_id,
                }
                for row in rows
            }

        except Exception as exc:
            _log.warning("DataExporter: failed to load DB meta: %s — exporting without meta", exc)
            return {}
