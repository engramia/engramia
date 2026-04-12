# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""CLI tests for engramia/cli/main.py.

Uses typer.testing.CliRunner so commands run in-process without a real API
server or embedding provider. Commands that require httpx (keys create/list/
revoke) or a live PostgreSQL instance (keys bootstrap) are excluded — they
belong in integration tests.

Run:
    pytest tests/test_cli.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from engramia.cli.main import app
from tests.conftest import FakeEmbeddings

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_storage(storage, n: int = 3) -> list[str]:
    """Learn n patterns into storage using FakeEmbeddings. Returns task strings."""
    from engramia.memory import Memory

    mem = Memory(embeddings=FakeEmbeddings(), storage=storage)
    tasks = [f"task number {i}: process data file" for i in range(n)]
    for i, task in enumerate(tasks):
        mem.learn(task=task, code=f"code_{i}()", eval_score=7.0 + i * 0.5)
    return tasks


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_new_directory(self, tmp_path):
        target = tmp_path / "new_data"
        result = runner.invoke(app, ["init", "--path", str(target)])
        assert result.exit_code == 0
        assert target.exists()
        assert target.is_dir()

    def test_already_exists_exits_zero(self, tmp_path):
        result = runner.invoke(app, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "already exists" in result.output.lower()

    def test_output_contains_next_steps(self, tmp_path):
        target = tmp_path / "init_test"
        result = runner.invoke(app, ["init", "--path", str(target)])
        assert "serve" in result.output
        assert "status" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_empty_storage_shows_zero(self, tmp_path):
        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_shows_pattern_count(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=2)

        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "2" in result.output

    def test_shows_runs_after_learn(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=1)

        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        # At least "1" must appear (run count or pattern count)
        assert "1" in result.output


# ---------------------------------------------------------------------------
# aging
# ---------------------------------------------------------------------------


class TestAging:
    def test_empty_storage_no_prune(self, tmp_path):
        result = runner.invoke(app, ["aging", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "0" in result.output or "no patterns" in result.output.lower()

    def test_aging_runs_without_error(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=3)

        result = runner.invoke(app, ["aging", "--path", str(tmp_path)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


class TestRecall:
    def test_recall_no_results(self, tmp_path):
        with patch("engramia.cli.main._make_embeddings", return_value=FakeEmbeddings()):
            result = runner.invoke(app, ["recall", "unrelated obscure task xyz", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "no matching" in result.output.lower()

    def test_recall_finds_seeded_pattern(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=3)

        with patch("engramia.cli.main._make_embeddings", return_value=FakeEmbeddings()):
            result = runner.invoke(app, ["recall", "process data file", "--path", str(tmp_path)])
        assert result.exit_code == 0
        # Table header or pattern content should be present
        assert "Score" in result.output or "task" in result.output.lower()

    def test_recall_limit_flag(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=5)

        with patch("engramia.cli.main._make_embeddings", return_value=FakeEmbeddings()):
            result = runner.invoke(app, ["recall", "process data file", "--limit", "2", "--path", str(tmp_path)])
        assert result.exit_code == 0

    def test_recall_missing_api_key_exits_nonzero(self, tmp_path):
        """Without OPENAI_API_KEY and without local embeddings, should exit 1."""
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "ENGRAMIA_LOCAL_EMBEDDINGS")}
        with patch.dict(os.environ, env, clear=True):
            result = runner.invoke(app, ["recall", "some task", "--path", str(tmp_path)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------


class TestReindex:
    def test_reindex_empty_storage(self, tmp_path):
        with patch("engramia.cli.main._make_embeddings", return_value=FakeEmbeddings()):
            result = runner.invoke(app, ["reindex", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "nothing" in result.output.lower() or "no pattern" in result.output.lower()

    def test_reindex_seeded_storage(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=3)

        with patch("engramia.cli.main._make_embeddings", return_value=FakeEmbeddings()):
            result = runner.invoke(app, ["reindex", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "3" in result.output

    def test_reindex_dry_run_does_not_write(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=2)

        # Capture modification time of files before
        files_before = {f: f.stat().st_mtime for f in tmp_path.rglob("*.json")}

        with patch("engramia.cli.main._make_embeddings", return_value=FakeEmbeddings()):
            result = runner.invoke(app, ["reindex", "--dry-run", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "dry" in result.output.lower()

        # No files should have been modified
        for f, mtime in files_before.items():
            if f.exists():
                assert f.stat().st_mtime == mtime, f"{f} was modified during dry run"


# ---------------------------------------------------------------------------
# governance retention
# ---------------------------------------------------------------------------


class TestGovernanceRetention:
    def test_retention_empty_storage(self, tmp_path):
        result = runner.invoke(app, ["governance", "retention", "--path", str(tmp_path), "--days", "365"])
        assert result.exit_code == 0
        assert "retention" in result.output.lower() or "no patterns" in result.output.lower()

    def test_retention_dry_run_flag(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=2)

        result = runner.invoke(app, ["governance", "retention", "--path", str(tmp_path), "--dry-run", "--days", "365"])
        assert result.exit_code == 0
        assert "dry" in result.output.lower()

    def test_retention_does_not_delete_fresh_patterns(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=2)

        # Fresh patterns with 365-day retention → nothing deleted
        result = runner.invoke(app, ["governance", "retention", "--path", str(tmp_path), "--days", "365"])
        assert result.exit_code == 0
        # Pattern count should still be 2
        from engramia.core.success_patterns import SuccessPatternStore

        assert SuccessPatternStore(storage).get_count() == 2


# ---------------------------------------------------------------------------
# governance export
# ---------------------------------------------------------------------------


class TestGovernanceExport:
    def test_export_empty_storage_outputs_nothing(self, tmp_path):
        result = runner.invoke(app, ["governance", "export", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_export_to_stdout_is_valid_ndjson(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=2)

        result = runner.invoke(app, ["governance", "export", "--path", str(tmp_path)])
        assert result.exit_code == 0
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)  # must be valid JSON
            assert "key" in obj

    def test_export_to_file(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=3)

        out_file = tmp_path / "export.ndjson"
        result = runner.invoke(app, ["governance", "export", "--output", str(out_file), "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert out_file.exists()
        lines = out_file.read_text().strip().splitlines()
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# governance purge-project
# ---------------------------------------------------------------------------


class TestGovernancePurgeProject:
    def test_purge_with_yes_flag(self, tmp_path):
        from engramia.providers.json_storage import JSONStorage

        storage = JSONStorage(path=tmp_path)
        _seed_storage(storage, n=2)

        result = runner.invoke(
            app,
            ["governance", "purge-project", "default", "--yes", "--path", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "wiped" in result.output.lower() or "deleted" in result.output.lower()

    def test_purge_without_yes_aborts(self, tmp_path):
        # CliRunner input="" sends empty input → confirmation fails → abort
        result = runner.invoke(
            app,
            ["governance", "purge-project", "default", "--path", str(tmp_path)],
            input="\n",  # empty → not confirmed
        )
        # Should abort (exit 1) without deleting anything
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# serve (error path only — cannot start real uvicorn in tests)
# ---------------------------------------------------------------------------


class TestServe:
    def test_serve_exits_without_uvicorn(self, tmp_path):
        """If uvicorn is not installed, serve should exit with code 1."""
        import builtins

        real_import = builtins.__import__

        def _block_uvicorn(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block_uvicorn):
            result = runner.invoke(app, ["serve"])
        assert result.exit_code == 1
