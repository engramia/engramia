"""Tests for the agent-brain CLI (Typer, no external services)."""

import os

import pytest
from typer.testing import CliRunner

from engramia.cli.main import app

runner = CliRunner()


class TestInitCommand:
    def test_init_creates_directory(self, tmp_path):
        target = str(tmp_path / "new_brain")
        result = runner.invoke(app, ["init", "--path", target])
        assert result.exit_code == 0
        assert os.path.isdir(target)

    def test_init_existing_directory(self, tmp_path):
        result = runner.invoke(app, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "already exists" in result.output


class TestStatusCommand:
    def test_status_empty_storage(self, tmp_path):
        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Pattern" in result.output or "Metric" in result.output

    def test_status_shows_zero_runs(self, tmp_path):
        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "0" in result.output


class TestAgingCommand:
    def test_aging_empty_storage(self, tmp_path):
        result = runner.invoke(app, ["aging", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "no patterns pruned" in result.output.lower()


class TestRecallCommand:
    def test_recall_requires_embeddings_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ENGRAMIA_LOCAL_EMBEDDINGS", raising=False)
        result = runner.invoke(app, ["recall", "some task", "--path", str(tmp_path)])
        assert result.exit_code == 1
        assert "No embedding provider" in result.output

    def test_recall_empty_storage_no_matches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ENGRAMIA_LOCAL_EMBEDDINGS", "1")
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
        except ImportError:
            pytest.skip("sentence-transformers not installed")

        result = runner.invoke(app, ["recall", "some task", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "No matching" in result.output
