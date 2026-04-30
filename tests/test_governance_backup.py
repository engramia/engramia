# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Class-level tests for ``governance.backup.BackupExporter``.

The HTTP route at ``/governance/backup`` has integration tests in
``tests/test_api/test_backup_download.py``. Those exercise auth, RBAC,
and Team+ paywalling — but they do not assert that the exported NDJSON
honours the security contract:

  - Excluded tables (``tenant_credentials``, ``audit_log``,
    ``billing_subscriptions``, ``api_keys``) **must never** appear in
    any SELECT statement.
  - Every query must be tenant-scoped via the ``:tid`` parameter.
  - The envelope must be header → rows → footer; absence of footer is
    the integrity marker so a truncated download is detectable.

A future PR forgetting to exclude a sensitive table — or accidentally
removing the tenant filter from a SELECT — would not fail any current
test. This file closes that gap.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from engramia.governance.backup import BackupExporter

# Tables that **must never** be reachable through BackupExporter.stream().
_EXCLUDED_TABLES = (
    "tenant_credentials",
    "audit_log",
    "billing_subscriptions",
    "stripe_events",
    "stripe_customers",
    "api_keys",
    "revoked_jtis",
    "cloud_users",  # PII; restored from auth backups separately
)


# ---------------------------------------------------------------------------
# Fake engine — records every SQL executed
# ---------------------------------------------------------------------------


class _FakeRow:
    def __init__(self, mapping: dict):
        self._mapping = mapping


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def __iter__(self):
        return iter(_FakeRow(r) for r in self._rows)


class _FakeConn:
    def __init__(self, eng: "_FakeEngine"):
        self._eng = eng

    def execution_options(self, **_kwargs):
        return self  # chainable; we ignore the options for testing

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self._eng.executed.append({"sql": sql, "params": dict(params or {})})

        # If a table-specific error was registered, raise it.
        for tbl, err in self._eng.errors.items():
            if re.search(rf"\bFROM\s+{tbl}\b", sql) or re.search(rf"\b{tbl}\s+WHERE\b", sql):
                raise err

        # Match the leading FROM <table> to decide which rows to return.
        m = re.search(r"FROM\s+(\w+)", sql)
        if m and m.group(1) in self._eng.tables:
            return _FakeResult(self._eng.tables[m.group(1)])
        return _FakeResult([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.errors: dict[str, Exception] = {}
        self.executed: list[dict] = []

    def connect(self):
        return _FakeConn(self)


@pytest.fixture
def engine():
    return _FakeEngine()


def _drain(exporter: BackupExporter, tenant_id: str) -> list[dict]:
    """Collect the NDJSON envelope into a list of parsed dicts."""
    chunks: list[dict] = []
    for line in exporter.stream(tenant_id):
        # Each yield is a single JSON object terminated with '\n'.
        assert line.endswith("\n"), "BackupExporter must terminate each line with \\n"
        for sub in line.splitlines():
            if sub:
                chunks.append(json.loads(sub))
    return chunks


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_rejects_none_engine(self):
        with pytest.raises(ValueError, match="engine"):
            BackupExporter(None)

    def test_accepts_engine(self, engine):
        # No-op — should not raise.
        BackupExporter(engine)


# ---------------------------------------------------------------------------
# Envelope shape: header → rows → footer
# ---------------------------------------------------------------------------


class TestEnvelopeShape:
    def test_header_first_then_footer_last(self, engine):
        engine.tables["memory_data"] = [{"key": "a"}, {"key": "b"}]
        out = _drain(BackupExporter(engine), "tenant-1")
        assert out[0]["kind"] == "header"
        assert out[-1]["kind"] == "footer"

    def test_header_carries_tenant_and_table_list(self, engine):
        out = _drain(BackupExporter(engine), "tenant-xyz")
        header = out[0]
        assert header["version"] == 1
        assert header["tenant_id"] == "tenant-xyz"
        # ISO 8601 timestamp.
        assert "T" in header["exported_at"]
        # The header tables list MUST match the order things will be streamed.
        assert isinstance(header["tables"], list)
        assert "memory_data" in header["tables"]
        assert "memory_embeddings" in header["tables"]

    def test_footer_row_count_matches_total_rows_yielded(self, engine):
        engine.tables["memory_data"] = [{"key": f"k-{i}"} for i in range(7)]
        engine.tables["analytics_events"] = [{"kind": "x"}, {"kind": "y"}]
        out = _drain(BackupExporter(engine), "t")
        rows = [c for c in out if c["kind"] == "row"]
        footer = out[-1]
        assert footer["kind"] == "footer"
        assert footer["row_count"] == len(rows) == 9
        # Per-table accounting matches.
        assert footer["table_counts"]["memory_data"] == 7
        assert footer["table_counts"]["analytics_events"] == 2

    def test_empty_tenant_still_emits_header_and_footer(self, engine):
        out = _drain(BackupExporter(engine), "ghost")
        assert out[0]["kind"] == "header"
        assert out[-1]["kind"] == "footer"
        assert out[-1]["row_count"] == 0
        assert all(c["kind"] != "row" for c in out)

    def test_each_row_has_canonical_envelope(self, engine):
        engine.tables["memory_data"] = [{"key": "a", "value": "v"}]
        out = _drain(BackupExporter(engine), "t")
        rows = [c for c in out if c["kind"] == "row"]
        assert len(rows) == 1
        r = rows[0]
        assert r["version"] == 1
        assert r["kind"] == "row"
        assert r["table"] == "memory_data"
        assert r["data"] == {"key": "a", "value": "v"}


# ---------------------------------------------------------------------------
# Security contract: excluded tables + tenant filter
# ---------------------------------------------------------------------------


class TestSecurityContract:
    @pytest.mark.parametrize("excluded_table", _EXCLUDED_TABLES)
    def test_excluded_table_never_queried(self, engine, excluded_table):
        """A future code change adding a sensitive table to the loop fails here."""
        list(BackupExporter(engine).stream("t"))
        for ex in engine.executed:
            assert excluded_table not in ex["sql"], (
                f"Sensitive table {excluded_table!r} appeared in BackupExporter "
                f"SQL — backup must NEVER stream this table. Offending SQL:\n{ex['sql']}"
            )

    def test_every_query_is_tenant_scoped(self, engine):
        list(BackupExporter(engine).stream("t-only-this"))
        # Every executed query must bind the :tid parameter and use it in WHERE.
        for ex in engine.executed:
            assert ex["params"].get("tid") == "t-only-this", (
                f"Query missing tenant binding: {ex['sql']}"
            )
            assert ":tid" in ex["sql"], f"Query missing :tid placeholder: {ex['sql']}"

    def test_excluded_tables_appear_neither_in_header_nor_in_table_counts(self, engine):
        out = _drain(BackupExporter(engine), "t")
        header = out[0]
        footer = out[-1]
        for ex_table in _EXCLUDED_TABLES:
            assert ex_table not in header["tables"], (
                f"Header advertises excluded table: {ex_table}"
            )
            assert ex_table not in footer["table_counts"], (
                f"Footer counts excluded table: {ex_table}"
            )


# ---------------------------------------------------------------------------
# Resilience: per-table error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_table_error_emits_error_envelope_and_continues(self, engine):
        """One broken table must NOT abort the dump — operator gets partial data."""
        engine.tables["memory_data"] = [{"key": "a"}]
        engine.errors["memory_embeddings"] = RuntimeError("relation does not exist")
        engine.tables["projects"] = [{"id": "p1", "tenant_id": "t"}]

        out = _drain(BackupExporter(engine), "t")

        # We still get the footer.
        assert out[-1]["kind"] == "footer"
        # We get an error envelope for the broken table.
        errors = [c for c in out if c["kind"] == "error"]
        assert len(errors) == 1
        assert errors[0]["table"] == "memory_embeddings"
        assert "relation does not exist" in errors[0]["message"]
        # Tables before AND after the broken one are still streamed.
        rows = [c for c in out if c["kind"] == "row"]
        assert any(r["table"] == "memory_data" for r in rows)
        assert any(r["table"] == "projects" for r in rows)

    def test_failed_table_count_is_zero_in_footer(self, engine):
        engine.errors["jobs"] = RuntimeError("boom")
        out = _drain(BackupExporter(engine), "t")
        footer = out[-1]
        assert footer["table_counts"].get("jobs", 0) == 0


# ---------------------------------------------------------------------------
# Output format: NDJSON, JSON-encodable values
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_lines_are_individually_json_parseable(self, engine):
        engine.tables["memory_data"] = [{"key": "a"}, {"key": "b"}, {"key": "c"}]
        chunks = list(BackupExporter(engine).stream("t"))
        for chunk in chunks:
            for line in chunk.splitlines():
                if line:
                    json.loads(line)  # must not raise

    def test_datetime_and_decimal_serialised_as_strings(self, engine):
        """NDJSON consumers re-parse ISO timestamps; default=str must apply."""
        import datetime
        from decimal import Decimal

        engine.tables["memory_data"] = [
            {"key": "k", "created_at": datetime.datetime(2026, 4, 30, 12, 0, 0), "score": Decimal("0.95")}
        ]
        out = _drain(BackupExporter(engine), "t")
        rows = [c for c in out if c["kind"] == "row"]
        assert len(rows) == 1
        data = rows[0]["data"]
        # `default=str` stringifies non-JSON-native types.
        assert isinstance(data["created_at"], str)
        assert "2026" in data["created_at"]
        assert isinstance(data["score"], str)
        assert data["score"] == "0.95"

    def test_each_yielded_chunk_terminates_with_newline(self, engine):
        engine.tables["memory_data"] = [{"key": "a"}]
        for chunk in BackupExporter(engine).stream("t"):
            assert chunk.endswith("\n")


# ---------------------------------------------------------------------------
# Schema: column whitelist (no SELECT *)
# ---------------------------------------------------------------------------


class TestSchema:
    def test_no_select_star_anywhere(self, engine):
        """SELECT * leaks new columns automatically — must use explicit lists."""
        list(BackupExporter(engine).stream("t"))
        for ex in engine.executed:
            assert "SELECT *" not in ex["sql"].upper(), (
                f"BackupExporter must not use SELECT * — found: {ex['sql']}"
            )

    def test_memory_embeddings_uses_text_cast_for_pgvector(self, engine):
        """embedding::text is the contract that lets the consumer re-parse vectors."""
        list(BackupExporter(engine).stream("t"))
        emb_query = next(
            (e for e in engine.executed if "memory_embeddings" in e["sql"]), None
        )
        assert emb_query is not None
        assert "embedding::text" in emb_query["sql"]
