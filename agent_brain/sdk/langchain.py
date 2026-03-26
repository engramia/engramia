"""LangChain integration for Agent Brain.

Requires the ``langchain`` extra:
    pip install agent-brain[langchain]

Usage:
    from agent_brain.sdk.langchain import BrainCallback

    callback = BrainCallback(brain, auto_learn=True, auto_recall=True)
    chain = LLMChain(llm=llm, prompt=prompt, callbacks=[callback])
    # Brain automatically learns from successful runs and recalls relevant context.
"""

import logging
from typing import Any

from agent_brain.brain import Brain

_log = logging.getLogger(__name__)

_INSTALL_MSG = "LangChain callback requires langchain-core. Install with: pip install agent-brain[langchain]"


class BrainCallback:
    """LangChain callback handler that integrates with Agent Brain.

    Automatically learns from chain/tool runs and optionally recalls
    relevant patterns before a chain starts.

    Args:
        brain: Brain instance to use for learn/recall.
        auto_learn: If True, call brain.learn() after successful chain runs.
        auto_recall: If True, call brain.recall() before chain runs and
            attach context to the run metadata.
        min_score: Minimum eval score to consider a run successful for learning.
            Below this threshold, the run is not stored.
        recall_limit: Number of patterns to recall before a chain run.
    """

    def __init__(
        self,
        brain: Brain,
        auto_learn: bool = True,
        auto_recall: bool = True,
        min_score: float = 5.0,
        recall_limit: int = 3,
    ) -> None:
        try:
            from langchain_core.callbacks import BaseCallbackHandler  # noqa: F401
        except ImportError:
            raise ImportError(_INSTALL_MSG) from None
        self._brain = brain
        self._auto_learn = auto_learn
        self._auto_recall = auto_recall
        self._min_score = min_score
        self._recall_limit = recall_limit
        # Track in-progress chains for learn
        self._active_chains: dict[str, dict[str, Any]] = {}

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain starts. Recalls relevant patterns if auto_recall is enabled."""
        task = _extract_task(inputs)
        chain_id = str(run_id) if run_id else str(id(inputs))
        self._active_chains[chain_id] = {"task": task, "inputs": inputs}

        if self._auto_recall and task:
            try:
                matches = self._brain.recall(task=task, limit=self._recall_limit)
                if matches:
                    context = [
                        {
                            "task": m.pattern.task,
                            "code": m.pattern.design.get("code", ""),
                            "similarity": m.similarity,
                            "reuse_tier": m.reuse_tier,
                        }
                        for m in matches
                    ]
                    _log.info(
                        "BrainCallback: recalled %d patterns for task %r",
                        len(context),
                        task[:80],
                    )
                    # Store recalled context on the active chain for downstream use
                    self._active_chains[chain_id]["recalled"] = context
            except Exception as exc:
                _log.warning("BrainCallback recall failed: %s", exc)

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain completes. Learns from the run if auto_learn is enabled."""
        chain_id = str(run_id) if run_id else None
        chain_info = self._active_chains.pop(chain_id, None) if chain_id else None

        if not self._auto_learn or not chain_info:
            return

        task = chain_info.get("task", "")
        if not task:
            return

        output_text = _extract_output(outputs)
        code = output_text  # In LangChain, the "code" is typically the output

        try:
            self._brain.learn(
                task=task,
                code=code or "(no output)",
                eval_score=self._min_score,
                output=output_text,
            )
            _log.info("BrainCallback: learned from chain run for task %r", task[:80])
        except Exception as exc:
            _log.warning("BrainCallback learn failed: %s", exc)

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Clean up tracking on chain failure."""
        chain_id = str(run_id) if run_id else None
        if chain_id:
            self._active_chains.pop(chain_id, None)

    def get_recalled_context(self, run_id: str) -> list[dict] | None:
        """Retrieve patterns recalled for a specific chain run.

        Args:
            run_id: The run ID from on_chain_start.

        Returns:
            List of recalled pattern dicts, or None if no recall was done.
        """
        chain_info = self._active_chains.get(run_id)
        if chain_info:
            return chain_info.get("recalled")
        return None


def _extract_task(inputs: dict[str, Any]) -> str:
    """Best-effort extraction of a task description from chain inputs."""
    # Common LangChain input keys
    for key in ("input", "question", "query", "task", "prompt", "text"):
        if key in inputs and isinstance(inputs[key], str):
            return inputs[key]
    # Fallback: first string value
    for v in inputs.values():
        if isinstance(v, str) and len(v) > 5:
            return v
    return ""


def _extract_output(outputs: dict[str, Any]) -> str:
    """Best-effort extraction of output text from chain outputs."""
    for key in ("output", "text", "result", "answer", "response"):
        if key in outputs and isinstance(outputs[key], str):
            return outputs[key]
    for v in outputs.values():
        if isinstance(v, str):
            return v
    return ""
