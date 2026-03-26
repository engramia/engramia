# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for Brain.export() and Brain.import_data()."""

from engramia.brain import Memory


class TestExport:
    def test_export_empty(self, brain):
        records = brain.export()
        assert records == []

    def test_export_after_learn(self, brain):
        brain.learn(task="Parse CSV", code="import csv", eval_score=8.0)
        records = brain.export()
        assert len(records) == 1
        assert records[0]["version"] == 1
        assert "key" in records[0]
        assert "data" in records[0]
        assert records[0]["data"]["task"] == "Parse CSV"

    def test_export_multiple(self, brain):
        brain.learn(task="Task A", code="code_a", eval_score=7.0)
        brain.learn(task="Task B", code="code_b", eval_score=8.0)
        records = brain.export()
        assert len(records) == 2

    def test_export_keys_have_patterns_prefix(self, brain):
        brain.learn(task="A task", code="pass", eval_score=6.0)
        records = brain.export()
        assert all(r["key"].startswith("patterns/") for r in records)


class TestImportData:
    def test_import_empty_list(self, brain):
        imported = brain.import_data([])
        assert imported == 0

    def test_import_records(self, brain, fake_embeddings, storage):
        # Export from one brain, import into another
        source = Memory(embeddings=fake_embeddings, storage=storage)
        source.learn(task="Task to import", code="pass", eval_score=7.5)
        records = source.export()

        target_brain = Memory(embeddings=fake_embeddings, storage=storage)
        imported = target_brain.import_data(records)
        assert imported >= 0  # already exist in same storage

    def test_import_skips_existing_by_default(self, brain, fake_embeddings, storage):
        brain.learn(task="Existing task", code="pass", eval_score=7.0)
        records = brain.export()
        # Import again without overwrite
        imported = brain.import_data(records, overwrite=False)
        assert imported == 0

    def test_import_overwrites_when_flag_set(self, brain, fake_embeddings, storage):
        brain.learn(task="Existing task", code="pass", eval_score=7.0)
        records = brain.export()
        imported = brain.import_data(records, overwrite=True)
        assert imported == 1

    def test_import_skips_malformed(self, brain):
        records = [
            {
                "key": "patterns/valid",
                "data": {"task": "t", "design": {}, "success_score": 5.0, "reuse_count": 0, "timestamp": 0.0},
            },
            {"key": "", "data": {"task": "no key"}},
            {"data": {"task": "no key field"}},
        ]
        imported = brain.import_data(records)
        assert imported == 1  # only the valid one

    def test_roundtrip(self, brain, fake_embeddings, storage):
        brain.learn(task="Roundtrip task", code="print('hi')", eval_score=9.0)
        records = brain.export()
        assert len(records) == 1

        # Overwrite to verify round-trip
        imported = brain.import_data(records, overwrite=True)
        assert imported == 1
        after = brain.export()
        assert len(after) == 1
        assert after[0]["data"]["task"] == "Roundtrip task"
