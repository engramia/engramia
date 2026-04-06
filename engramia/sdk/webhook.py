# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Lightweight Python SDK client for the Engramia REST API.

Usage:
    from engramia.sdk.webhook import EngramiaWebhook

    hook = EngramiaWebhook(url="http://localhost:8000", api_key="sk-...")
    hook.learn(task="Parse CSV", code=code, eval_score=8.5)
    matches = hook.recall(task="Read CSV and compute averages")

No extra dependencies — uses urllib from the standard library.
For advanced use cases (async, streaming), use httpx or requests directly.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30  # seconds


class EngramiaWebhookError(Exception):
    """Raised when an Engramia API call fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class EngramiaWebhook:
    """HTTP client for the Engramia REST API.

    Args:
        url: Base URL of the Engramia API (e.g. "http://localhost:8000").
        api_key: Optional Bearer token for authentication.
        timeout: Request timeout in seconds (default: 30).
    """

    def __init__(
        self,
        url: str,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def learn(
        self,
        task: str,
        code: str,
        eval_score: float,
        output: str | None = None,
    ) -> dict:
        """Record a successful agent run.

        Args:
            task: Task description.
            code: Agent source code.
            eval_score: Quality score 0-10.
            output: Optional captured output.

        Returns:
            Response dict with ``stored`` and ``pattern_count``.
        """
        body: dict[str, Any] = {
            "task": task,
            "code": code,
            "eval_score": eval_score,
        }
        if output is not None:
            body["output"] = output
        return self._post("/v1/learn", body)

    def recall(
        self,
        task: str,
        limit: int = 5,
        deduplicate: bool = True,
        eval_weighted: bool = True,
    ) -> list[dict]:
        """Find relevant patterns for a task.

        Args:
            task: Task to match against stored patterns.
            limit: Maximum number of matches.
            deduplicate: Group near-duplicate tasks.
            eval_weighted: Boost high-quality patterns.

        Returns:
            List of match dicts.
        """
        body = {
            "task": task,
            "limit": limit,
            "deduplicate": deduplicate,
            "eval_weighted": eval_weighted,
        }
        resp = self._post("/v1/recall", body)
        return resp.get("matches", [])

    def evaluate(
        self,
        task: str,
        code: str,
        output: str | None = None,
        num_evals: int = 3,
    ) -> dict:
        """Run multi-evaluator scoring.

        Args:
            task: Task the code solves.
            code: Agent source code.
            output: Optional captured output.
            num_evals: Number of evaluation runs.

        Returns:
            Response dict with scores and feedback.
        """
        body: dict[str, Any] = {
            "task": task,
            "code": code,
            "num_evals": num_evals,
        }
        if output is not None:
            body["output"] = output
        return self._post("/v1/evaluate", body)

    def compose(self, task: str) -> dict:
        """Decompose a task into a pipeline.

        Args:
            task: High-level task description.

        Returns:
            Response dict with stages and validation.
        """
        return self._post("/v1/compose", {"task": task})

    def feedback(self, task_type: str | None = None, limit: int = 5) -> list[str]:
        """Get recurring quality issues.

        Args:
            task_type: Optional filter by task type.
            limit: Maximum number of feedback strings.

        Returns:
            List of feedback strings.
        """
        params = f"?limit={limit}"
        if task_type:
            params += f"&task_type={urllib.parse.quote(task_type)}"
        resp = self._get(f"/v1/feedback{params}")
        return resp.get("feedback", [])

    def metrics(self) -> dict:
        """Get aggregate statistics.

        Returns:
            Metrics dict.
        """
        return self._get("/v1/metrics")

    def health(self) -> dict:
        """Health check.

        Returns:
            Health dict with status and storage type.
        """
        return self._get("/v1/health")

    def delete_pattern(self, pattern_key: str) -> bool:
        """Delete a stored pattern.

        Args:
            pattern_key: Pattern storage key.

        Returns:
            True if the pattern was deleted.
        """
        resp = self._delete(f"/v1/patterns/{pattern_key}")
        return resp.get("deleted", False)

    def run_aging(self) -> int:
        """Run pattern aging.

        Returns:
            Number of patterns pruned.
        """
        resp = self._post("/v1/aging", {})
        return resp.get("pruned", 0)

    def run_feedback_decay(self) -> int:
        """Run feedback decay.

        Returns:
            Number of feedback patterns pruned.
        """
        resp = self._post("/v1/feedback/decay", {})
        return resp.get("pruned", 0)

    def evolve_prompt(
        self,
        role: str,
        current_prompt: str,
        num_issues: int = 5,
    ) -> dict:
        """Generate an improved prompt based on recurring feedback.

        Args:
            role: Agent role (e.g. "coder", "eval", "architect").
            current_prompt: Current system prompt to improve.
            num_issues: Number of top issues to address.

        Returns:
            Response dict with improved_prompt, changes, accepted, reason.
        """
        return self._post(
            "/v1/evolve",
            {
                "role": role,
                "current_prompt": current_prompt,
                "num_issues": num_issues,
            },
        )

    def analyze_failures(self, min_count: int = 1) -> list[dict]:
        """Cluster failure patterns to identify systemic issues.

        Args:
            min_count: Minimum occurrence count for inclusion.

        Returns:
            List of cluster dicts with representative, members, total_count, avg_score.
        """
        resp = self._post("/v1/analyze-failures", {"min_count": min_count})
        return resp.get("clusters", [])

    def register_skills(self, pattern_key: str, skills: list[str]) -> int:
        """Associate skill tags with a stored pattern.

        Args:
            pattern_key: Storage key of the pattern to tag.
            skills: Skill tags to associate (e.g. ["csv_parsing", "statistics"]).

        Returns:
            Number of unique skills now registered for the pattern.
        """
        resp = self._post(
            "/v1/skills/register",
            {
                "pattern_key": pattern_key,
                "skills": skills,
            },
        )
        return resp.get("registered", 0)

    def find_by_skills(
        self,
        required: list[str],
        match_all: bool = True,
    ) -> list[dict]:
        """Find patterns that have the required skills.

        Args:
            required: Skill tags to search for.
            match_all: If True, pattern must have ALL required skills.

        Returns:
            List of match dicts.
        """
        resp = self._post(
            "/v1/skills/search",
            {
                "required": required,
                "match_all": match_all,
            },
        )
        return resp.get("matches", [])

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)

    def _get(self, path: str) -> dict:
        return self._request("GET", path)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self._url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
                content_type = resp.headers.get("Content-Type", "")
                if "json" not in content_type:
                    raise EngramiaWebhookError(
                        resp.status,
                        f"Unexpected Content-Type: {content_type}",
                    )
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode() if exc.fp else str(exc)
            raise EngramiaWebhookError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise EngramiaWebhookError(0, f"Connection failed: {exc.reason}") from exc
