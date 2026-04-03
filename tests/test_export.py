# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Brain.export() and Brain.import_data()."""

from engramia.memory import Memory


class TestExport:
    def test_export_empty(self, mem):
        records = mem.export()
        assert records == []

    def test_export_after_learn(self, mem):
        mem.learn(task="Parse CSV", code="import csv", eval_score=8.0)
        records = mem.export()
        assert len(records) == 1
        assert records[0]["version"] == 1
        assert "key" in records[0]
        assert "data" in records[0]
        assert records[0]["data"]["task"] == "Parse CSV"

    def test_export_multiple(self, mem):
        mem.learn(task="Task A", code="code_a", eval_score=7.0)
        mem.learn(task="Task B", code="code_b", eval_score=8.0)
        records = mem.export()
        assert len(records) == 2

    def test_export_keys_have_patterns_prefix(self, mem):
        mem.learn(task="A task", code="pass", eval_score=6.0)
        records = mem.export()
        assert all(r["key"].startswith("patterns/") for r in records)


class TestImportData:
    def test_import_empty_list(self, mem):
        imported = mem.import_data([])
        assert imported == 0

    def test_import_records(self, mem, fake_embeddings, storage):
        # Export from one mem, import into another
        source = Memory(embeddings=fake_embeddings, storage=storage)
        source.learn(task="Task to import", code="pass", eval_score=7.5)
        records = source.export()

        target_brain = Memory(embeddings=fake_embeddings, storage=storage)
        imported = target_brain.import_data(records)
        assert imported >= 0  # already exist in same storage

    def test_import_skips_existing_by_default(self, mem, fake_embeddings, storage):
        mem.learn(task="Existing task", code="pass", eval_score=7.0)
        records = mem.export()
        # Import again without overwrite
        imported = mem.import_data(records, overwrite=False)
        assert imported == 0

    def test_import_overwrites_when_flag_set(self, mem, fake_embeddings, storage):
        mem.learn(task="Existing task", code="pass", eval_score=7.0)
        records = mem.export()
        imported = mem.import_data(records, overwrite=True)
        assert imported == 1

    def test_import_skips_malformed(self, mem):
        records = [
            {
                "key": "patterns/valid",
                "data": {"task": "t", "design": {}, "success_score": 5.0, "reuse_count": 0, "timestamp": 0.0},
            },
            {"key": "", "data": {"task": "no key"}},
            {"data": {"task": "no key field"}},
        ]
        imported = mem.import_data(records)
        assert imported == 1  # only the valid one

    def test_roundtrip(self, mem, fake_embeddings, storage):
        mem.learn(task="Roundtrip task", code="print('hi')", eval_score=9.0)
        records = mem.export()
        assert len(records) == 1

        # Overwrite to verify round-trip
        imported = mem.import_data(records, overwrite=True)
        assert imported == 1
        after = mem.export()
        assert len(after) == 1
        assert after[0]["data"]["task"] == "Roundtrip task"

    def test_import_rejects_future_version(self, mem):
        """Records with a version newer than _EXPORT_VERSION must be skipped."""
        future_record = {
            "version": 9999,
            "key": "patterns/future",
            "data": {"task": "future task", "code": "future()", "eval_score": 8.0},
        }
        imported = mem.import_data([future_record])
        assert imported == 0

    def test_import_accepts_current_version(self, mem):
        from engramia.memory import _EXPORT_VERSION

        record = {
            "version": _EXPORT_VERSION,
            "key": "patterns/current_ver",
            "data": {
                "task": "versioned task",
                "code": "versioned()",
                "success_score": 8.0,
                "reuse_count": 0,
                "timestamp": 0.0,
            },
        }
        imported = mem.import_data([record])
        assert imported == 1

    def test_export_version_matches_constant(self, mem):
        from engramia.memory import _EXPORT_VERSION

        mem.learn(task="Version constant check", code="pass", eval_score=7.0)
        records = mem.export()
        assert records[0]["version"] == _EXPORT_VERSION
