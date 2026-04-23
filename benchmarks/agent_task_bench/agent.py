# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""gpt-4o-mini agent — generates a Python completion for a
HumanEval+ prompt, optionally with a context prefix produced by the
memory backend.

Single LLM call per task. Temperature 0 for determinism. Caller is
responsible for token accounting — :class:`Agent.generate` returns a
:class:`GenerationResult` that carries input / output token counts so
the runner can roll up cost.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a Python coding assistant. Given a function prompt you "
    "produce a COMPLETE, self-contained Python module that implements "
    "the function: include every import the function needs, the full "
    "`def <name>(...):` signature (copy it from the prompt), the "
    "docstring, and the body. Do not add prose, do not add markdown "
    "fences, do not add top-level test code. Your output is executed "
    "directly as a .py file; the caller appends the test harness "
    "afterwards."
)


@dataclass
class GenerationResult:
    completion: str
    input_tokens: int
    output_tokens: int
    raw_content: str  # un-sanitised LLM output, for debugging


class Agent:
    """Wraps the OpenAI client for HumanEval+ generation."""

    def __init__(self, model: str = "gpt-4o-mini", client: Any | None = None) -> None:
        self._model = model
        if client is None:
            from openai import OpenAI

            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY is required to run AgentTaskBench.")
            self._client = OpenAI()
        else:
            self._client = client

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str, *, context: str = "") -> GenerationResult:
        """Produce a function-body completion for ``prompt``.

        ``context`` is inserted BEFORE the prompt in the user message.
        It comes from the memory backend (a rendered recall summary);
        empty in the baseline configuration.
        """
        user_message = (
            (f"Prior relevant examples from memory:\n\n{context}\n\n---\n\n"
             if context else "")
            + "Implement the function below. Return the COMPLETE module: "
            + "copy the imports and `def` signature from the prompt verbatim, "
            + "then add the body. No markdown fences, no surrounding prose.\n\n"
            + prompt
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0.0,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        in_t = resp.usage.prompt_tokens if resp.usage else 0
        out_t = resp.usage.completion_tokens if resp.usage else 0

        completion = _strip_markdown_fence(raw)
        return GenerationResult(
            completion=completion,
            input_tokens=in_t,
            output_tokens=out_t,
            raw_content=raw,
        )


_FENCE_RE = re.compile(r"^\s*```(?:python)?\s*\n(.*?)\n```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_markdown_fence(text: str) -> str:
    """Remove a wrapping ```python ... ``` fence if the model added one."""
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1)
    # Some models return just the fence header with no closing; drop a
    # leading bare ``` line if present.
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
