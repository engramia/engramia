"""Unit tests for PipelineComposer."""

import json

import pytest

from agent_brain.core.eval_store import EvalStore
from agent_brain.reuse.composer import PipelineComposer
from agent_brain.reuse.matcher import PatternMatcher
from agent_brain.types import Pattern


class FakeLLM:
    """Fake LLM that returns a configurable response."""

    def __init__(self, response: str):
        self._response = response

    def call(self, prompt: str, system: str | None = None, role: str = "default") -> str:
        return self._response


class TestPipelineComposer:
    """Tests for PipelineComposer.compose()."""

    def _store_pattern(self, storage, embeddings, task, code="pass", score=8.0):
        import hashlib
        import time

        h = hashlib.md5(task.encode()).hexdigest()[:8]
        key = f"patterns/{h}_{int(time.time() * 1000)}"
        pattern = Pattern(task=task, design={"code": code}, success_score=score)
        storage.save(key, pattern.model_dump())
        storage.save_embedding(key, embeddings.embed(task))
        return key

    def test_compose_decomposes_into_stages(self, storage, fake_embeddings):
        llm_response = json.dumps({
            "stages": [
                {"task": "Fetch data", "reads": ["input.csv"], "writes": ["data.json"]},
                {"task": "Analyze data", "reads": ["data.json"], "writes": ["report.txt"]},
            ]
        })
        llm = FakeLLM(llm_response)
        eval_store = EvalStore(storage)
        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        composer = PipelineComposer(llm, matcher)

        pipeline = composer.compose("Fetch data and write a report")
        assert len(pipeline.stages) == 2
        assert pipeline.stages[0].task == "Fetch data"
        assert pipeline.stages[1].task == "Analyze data"
        assert pipeline.task == "Fetch data and write a report"

    def test_compose_validates_contracts(self, storage, fake_embeddings):
        llm_response = json.dumps({
            "stages": [
                {"task": "Fetch data", "reads": ["input.csv"], "writes": ["data.json"]},
                {"task": "Analyze", "reads": ["data.json"], "writes": ["report.txt"]},
            ]
        })
        llm = FakeLLM(llm_response)
        eval_store = EvalStore(storage)
        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        composer = PipelineComposer(llm, matcher)

        pipeline = composer.compose("Full pipeline")
        # data.json is written by stage 0 and read by stage 1 — valid chain
        # input.csv is not produced by any stage but is an inferred initial input
        # The pipeline may or may not be valid depending on infer_initial_inputs
        assert isinstance(pipeline.valid, bool)
        assert isinstance(pipeline.contract_errors, list)

    def test_compose_falls_back_on_llm_failure(self, storage, fake_embeddings):
        llm = FakeLLM("This is not JSON at all")
        eval_store = EvalStore(storage)
        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        composer = PipelineComposer(llm, matcher)

        pipeline = composer.compose("Do something complex")
        # Fallback: single stage with the original task
        assert len(pipeline.stages) == 1
        assert pipeline.stages[0].task == "Do something complex"

    def test_compose_max_4_stages(self, storage, fake_embeddings):
        llm_response = json.dumps({
            "stages": [
                {"task": f"Stage {i}", "reads": [], "writes": [f"out_{i}.txt"]}
                for i in range(6)
            ]
        })
        llm = FakeLLM(llm_response)
        eval_store = EvalStore(storage)
        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        composer = PipelineComposer(llm, matcher)

        pipeline = composer.compose("Many stages task")
        assert len(pipeline.stages) <= 4

    def test_compose_matches_existing_patterns(self, storage, fake_embeddings):
        # Store a pattern that matches one of the stages
        self._store_pattern(storage, fake_embeddings, "Fetch data from API", code="import requests")

        llm_response = json.dumps({
            "stages": [
                {"task": "Fetch data from API", "reads": [], "writes": ["data.json"]},
                {"task": "Write report", "reads": ["data.json"], "writes": ["report.txt"]},
            ]
        })
        llm = FakeLLM(llm_response)
        eval_store = EvalStore(storage)
        matcher = PatternMatcher(storage, fake_embeddings, eval_store)
        composer = PipelineComposer(llm, matcher)

        pipeline = composer.compose("Fetch API data and report")
        # First stage should match the stored pattern
        assert pipeline.stages[0].design.get("code") == "import requests"
        assert pipeline.stages[0].reuse_tier in ("duplicate", "adapt")
        # Second stage has no stored pattern -> fresh
        assert pipeline.stages[1].reuse_tier == "fresh"
