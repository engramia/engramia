"""Pipeline composition engine.

Decomposes a high-level task into sequential stages via LLM, then finds
the best matching pattern for each stage using PatternMatcher. Validates
the resulting pipeline with contract checking.

Max pipeline stages: 4.
"""

import logging

from agent_brain._util import extract_json_from_llm
from agent_brain.providers.base import LLMProvider

_log = logging.getLogger(__name__)
from agent_brain.reuse.contracts import infer_initial_inputs, validate_contracts
from agent_brain.reuse.matcher import PatternMatcher
from agent_brain.types import Pipeline, PipelineStage

_MAX_STAGES = 4

_DECOMPOSE_SYSTEM = """\
You are an expert AI pipeline architect.
Break a high-level task into 2–4 sequential pipeline stages.
Each stage must produce files consumed by the next stage.
Respond ONLY with valid JSON — no extra text."""

_DECOMPOSE_USER = """\
Task: {task}

Decompose into 2–4 ordered stages. Each stage reads files from previous stages or initial inputs.

Respond with:
{{
  "stages": [
    {{"task": "...", "reads": ["input.csv"], "writes": ["processed.json"]}},
    {{"task": "...", "reads": ["processed.json"], "writes": ["report.txt"]}}
  ]
}}"""



class PipelineComposer:
    """Composes multi-agent pipelines from stored patterns.

    Args:
        llm: LLM provider for task decomposition.
        matcher: PatternMatcher for finding per-stage patterns.
    """

    def __init__(self, llm: LLMProvider, matcher: PatternMatcher) -> None:
        self._llm = llm
        self._matcher = matcher

    def compose(self, task: str) -> Pipeline:
        """Build a multi-agent pipeline for *task*.

        Steps:
        1. LLM decomposes task into 2–4 stages.
        2. PatternMatcher finds best pattern per stage.
        3. Contract validation checks data-flow consistency.

        Args:
            task: High-level task description.

        Returns:
            Pipeline with stages, validity flag, and any contract errors.
        """
        stage_specs = self._decompose(task)
        initial_inputs = infer_initial_inputs(task)

        stages: list[PipelineStage] = []
        for spec in stage_specs[:_MAX_STAGES]:
            matches = self._matcher.find(spec["task"], limit=1)
            if matches:
                best = matches[0]
                stage = PipelineStage(
                    name=f"stage_{len(stages)}",
                    task=spec["task"],
                    design=best.pattern.design,
                    reads=spec.get("reads") or [],
                    writes=spec.get("writes") or [],
                    reuse_tier=best.reuse_tier,
                    similarity=best.similarity,
                )
            else:
                stage = PipelineStage(
                    name=f"stage_{len(stages)}",
                    task=spec["task"],
                    design={},
                    reads=spec.get("reads") or [],
                    writes=spec.get("writes") or [],
                    reuse_tier="fresh",
                    similarity=0.0,
                )
            stages.append(stage)

        contract_errors = validate_contracts(
            [{"name": s.name, "reads": s.reads, "writes": s.writes} for s in stages],
            initial_inputs=initial_inputs,
        )

        return Pipeline(
            task=task,
            stages=stages,
            valid=len(contract_errors) == 0,
            contract_errors=contract_errors,
        )

    def _decompose(self, task: str) -> list[dict]:
        """Ask LLM to decompose task into stage specs."""
        prompt = _DECOMPOSE_USER.format(task=task)
        response = self._llm.call(prompt=prompt, system=_DECOMPOSE_SYSTEM, role="architect")
        try:
            parsed = extract_json_from_llm(response)
            stages = parsed.get("stages", [])
            if not isinstance(stages, list) or not stages:
                raise ValueError("No stages returned")
            return stages
        except Exception as exc:
            _log.warning("LLM decomposition failed, falling back to single stage: %s", exc)
            return [{"task": task, "reads": [], "writes": ["output.json"]}]
