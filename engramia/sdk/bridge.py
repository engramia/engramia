# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia agent factory bridge.

Drop-in pre/post-run hooks for agent factories:

  1. ``recall_context(task)`` — returns a formatted string of relevant past
     patterns for injection into the system prompt *before* a run.
  2. ``learn_run(task, code, output, eval_score)`` — records the completed
     run *after* execution.

Mode selection (precedence: constructor args → env vars):

  ``ENGRAMIA_API_URL``   → REST mode  (uses :class:`~engramia.sdk.webhook.EngramiaWebhook`)
  ``ENGRAMIA_DATA_PATH`` → direct mode (imports :class:`~engramia.Memory` locally)

  If ``ENGRAMIA_API_URL`` is set it takes precedence over direct mode.

Example::

    from engramia.sdk.bridge import EngramiaBridge

    bridge = EngramiaBridge()                        # reads env vars

    # Explicit hooks
    context = bridge.before_run(task)                # inject into system prompt
    result  = my_agent(task, context=context)
    bridge.after_run(task, code=result.code,
                     output=result.output, success=result.ok)

    # Decorator
    @bridge.wrap
    def run_agent(task: str) -> dict:
        ...
        return {"code": ..., "output": ..., "success": True}
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)

_RECALL_HEADER = "## Relevant patterns from previous runs\n"
_RECALL_ENTRY_TPL = (
    "\n### {i}. {task} (score {score:.1f}, similarity {sim:.2f})\n"
    "```python\n{code}\n```\n"
)
_CODE_SNIPPET_MAX = 2_000  # chars per pattern in the injected context


def _format_matches(matches: list[Any]) -> str:
    """Format recall results (dicts or Match objects) into prompt-ready markdown."""
    if not matches:
        return ""
    parts = [_RECALL_HEADER]
    for i, m in enumerate(matches, 1):
        if isinstance(m, dict):
            pat = m.get("pattern", {})
            task = pat.get("task", "")
            score = pat.get("success_score", 0.0)
            sim = m.get("similarity", 0.0)
            code = pat.get("design", {}).get("code", "")
        else:
            task = m.pattern.task
            score = m.pattern.success_score
            sim = m.similarity
            code = m.pattern.design.get("code", "")
        parts.append(
            _RECALL_ENTRY_TPL.format(
                i=i,
                task=task,
                score=score,
                sim=sim,
                code=code[:_CODE_SNIPPET_MAX],
            )
        )
    return "".join(parts)


class EngramiaBridge:
    """Agent factory bridge for pre/post-run Engramia hooks.

    Args:
        api_url: REST API base URL. Falls back to ``ENGRAMIA_API_URL`` env var.
        api_key: Bearer token. Falls back to ``ENGRAMIA_API_KEY`` env var.
        data_path: Local JSON storage path. Falls back to ``ENGRAMIA_DATA_PATH``
            (default: ``./brain_data``).
        recall_limit: Max patterns to inject per run (default: 3).
        auto_evaluate: Call ``/evaluate`` after a run when no score is provided
            (default: ``True``).
        min_score_to_learn: Skip recording runs below this threshold (default: 5.0).
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        data_path: str | None = None,
        recall_limit: int = 3,
        auto_evaluate: bool = True,
        min_score_to_learn: float = 5.0,
    ) -> None:
        self._api_url = api_url or os.environ.get("ENGRAMIA_API_URL")
        self._api_key = api_key or os.environ.get("ENGRAMIA_API_KEY")
        self._data_path = data_path or os.environ.get("ENGRAMIA_DATA_PATH", "./engramia_data")
        self._recall_limit = recall_limit
        self._auto_evaluate = auto_evaluate
        self._min_score = min_score_to_learn
        self._client: Any = None  # lazily initialised on first call

    # ------------------------------------------------------------------
    # Client initialisation
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if self._api_url:
            from engramia.sdk.webhook import EngramiaWebhook

            self._client = EngramiaWebhook(url=self._api_url, api_key=self._api_key)
            _log.info("EngramiaBridge: REST mode → %s", self._api_url)
        else:
            # Ensure the factory picks up the configured path.
            os.environ.setdefault("ENGRAMIA_DATA_PATH", self._data_path)
            from engramia import Memory
            from engramia._factory import make_embeddings, make_llm, make_storage

            self._client = Memory(
                embeddings=make_embeddings(),
                storage=make_storage(),
                llm=make_llm(),
            )
            _log.info("EngramiaBridge: direct mode → %s", self._data_path)

        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recall_context(self, task: str, limit: int | None = None) -> str:
        """Return formatted past patterns ready for system-prompt injection.

        Safe to call unconditionally — returns an empty string on any error so
        the agent run is never blocked.

        Args:
            task: Natural-language task description.
            limit: Override ``recall_limit`` for this call.

        Returns:
            Markdown string (empty if no relevant patterns found or on error).
        """
        try:
            client = self._get_client()
            matches = client.recall(task=task, limit=limit or self._recall_limit)
            ctx = _format_matches(matches)
            if ctx:
                _log.debug(
                    "EngramiaBridge: recalled %d patterns for task %.60s…",
                    len(matches),
                    task,
                )
            return ctx
        except Exception:
            _log.exception("EngramiaBridge.recall_context failed — continuing without context")
            return ""

    def learn_run(
        self,
        task: str,
        code: str,
        output: str | None = None,
        eval_score: float | None = None,
    ) -> None:
        """Record a completed agent run.

        If *eval_score* is ``None`` and ``auto_evaluate=True`` an evaluation is
        performed automatically (3 runs, median score).  Runs below
        ``min_score_to_learn`` are silently skipped.  Never raises.

        Args:
            task: Task description.
            code: Agent-generated source code.
            output: Captured stdout / agent output (optional).
            eval_score: Pre-computed quality score 0-10 (optional).
        """
        try:
            client = self._get_client()
            score = eval_score

            if score is None and self._auto_evaluate:
                score = self._auto_score(client, task, code, output)

            if score is None:
                score = 6.0  # conservative default when evaluation unavailable

            if score < self._min_score:
                _log.info(
                    "EngramiaBridge: score %.1f < min %.1f — skipping learn for task %.60s…",
                    score,
                    self._min_score,
                    task,
                )
                return

            client.learn(task=task, code=code, eval_score=score, output=output)
            _log.info("EngramiaBridge: learned run (score=%.1f, task=%.60s…)", score, task)
        except Exception:
            _log.exception("EngramiaBridge.learn_run failed — run not recorded")

    def before_run(self, task: str) -> str:
        """Pre-run hook: recall relevant patterns.

        Call this before invoking the agent and append the returned string to the
        system prompt.

        Args:
            task: Task the agent is about to execute.

        Returns:
            Formatted context string (empty string if no matches or on error).
        """
        return self.recall_context(task)

    def after_run(
        self,
        task: str,
        code: str,
        output: str | None = None,
        eval_score: float | None = None,
        success: bool = True,
    ) -> None:
        """Post-run hook: record the completed run.

        Failed runs (``success=False``) are not recorded.

        Args:
            task: Task description.
            code: Agent-generated source code.
            output: Captured stdout / agent output (optional).
            eval_score: Pre-computed quality score 0-10 (optional).
            success: Set to ``False`` to skip recording (e.g. on exception).
        """
        if not success:
            _log.debug("EngramiaBridge.after_run: success=False — skipping learn")
            return
        self.learn_run(task=task, code=code, output=output, eval_score=eval_score)

    def wrap(self, fn: Callable | None = None, *, task_arg: str = "task") -> Callable:
        """Decorator that wraps an agent function with recall/learn hooks.

        The wrapped function must:
        - accept a parameter named *task_arg* (default ``"task"``)
        - return a :class:`dict` with keys ``code`` (str), ``output`` (str,
          optional), ``success`` (bool, default ``True``), and optionally
          ``eval_score`` (float).

        The injected recall context is passed as ``_engramia_context`` keyword
        argument if the wrapped function accepts ``**kwargs`` or that parameter
        explicitly.

        Example::

            @bridge.wrap
            def run_agent(task: str, **kwargs) -> dict:
                ctx = kwargs.get("_engramia_context", "")
                ...
                return {"code": generated_code, "output": stdout, "success": True}

        Args:
            fn: Function to decorate (when used as ``@bridge.wrap`` without call).
            task_arg: Name of the task parameter in the wrapped function.

        Returns:
            Decorated callable.
        """

        def decorator(func: Callable) -> Callable:
            sig = inspect.signature(func)
            _accepts_context = (
                "_engramia_context" in sig.parameters
                or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
            )

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Resolve task value from positional or keyword args.
                task: str | None = kwargs.get(task_arg)
                if task is None:
                    params = list(sig.parameters.keys())
                    if task_arg in params:
                        idx = params.index(task_arg)
                        if idx < len(args):
                            task = args[idx]

                context = self.before_run(task) if task else ""
                if context and _accepts_context:
                    kwargs.setdefault("_engramia_context", context)

                result = func(*args, **kwargs)

                if task and isinstance(result, dict):
                    self.after_run(
                        task=task,
                        code=result.get("code", ""),
                        output=result.get("output"),
                        eval_score=result.get("eval_score"),
                        success=result.get("success", True),
                    )
                return result

            return wrapper

        if fn is not None:
            return decorator(fn)
        return decorator

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auto_score(
        self,
        client: Any,
        task: str,
        code: str,
        output: str | None,
    ) -> float:
        """Call evaluate and extract the median score; falls back to 6.0."""
        try:
            result = client.evaluate(task=task, code=code, output=output, num_evals=3)
            if isinstance(result, dict):
                score = result.get("median_score") or result.get("overall")
            else:
                score = result.median_score
            if score is not None:
                return float(score)
        except Exception:
            _log.exception("EngramiaBridge: auto-evaluate failed")
        return 6.0
