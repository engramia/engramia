# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Engramia load test — Locust.

Tests the three primary API endpoints:

  POST /v1/learn   — write path (LLM-heavy, expensive)
  POST /v1/recall  — read path  (embedding + vector search)
  GET  /v1/health  — health check (cheap, DB-less)

Usage
-----
Install locust (not in the main requirements):

    pip install locust

Run against a local dev server:

    locust -f tests/load/locustfile.py \
        --host http://localhost:8000 \
        --users 20 --spawn-rate 2 --run-time 60s --headless \
        --html tests/load/results_latest.html

Environment variables:

    ENGRAMIA_LOAD_API_KEY  — API key (default: "test-load-key")
    ENGRAMIA_LOAD_RATIO    — learn:recall ratio 0–1, default 0.2
                             (0.2 means 20% learn, 80% recall, matching prod traffic)

Performance baseline
--------------------
See tests/load/results_baseline.md for the pre-computed reference numbers
against a single-process Uvicorn on a Hetzner CX23 (2 vCPU, 4 GB RAM).
"""

import os
import random

from locust import HttpUser, between, task

_API_KEY = os.environ.get("ENGRAMIA_LOAD_API_KEY", "test-load-key")
_LEARN_RATIO = float(os.environ.get("ENGRAMIA_LOAD_RATIO", "0.2"))

# ---------------------------------------------------------------------------
# Synthetic payloads — realistic but deterministic so recall has warm patterns
# ---------------------------------------------------------------------------

_LEARN_PAYLOADS = [
    {
        "instruction": "When writing Python async code always use asyncio.TaskGroup for fan-out.",
        "outcome": "Reduced timeout bugs in production by grouping related coroutines.",
        "eval_score": 8.5,
        "tags": ["python", "async"],
    },
    {
        "instruction": "Validate every Pydantic model at the API boundary before persisting.",
        "outcome": "Eliminated a class of silent data-corruption bugs.",
        "eval_score": 9.0,
        "tags": ["pydantic", "validation"],
    },
    {
        "instruction": "Use expand-contract for PostgreSQL schema migrations in rolling deploys.",
        "outcome": "Zero-downtime migrations across three production releases.",
        "eval_score": 9.5,
        "tags": ["postgres", "migrations", "devops"],
    },
    {
        "instruction": "Cache OpenAI embedding responses keyed by SHA-256 of the input text.",
        "outcome": "Reduced embedding API cost by ~60% on repeat queries.",
        "eval_score": 8.0,
        "tags": ["openai", "cost"],
    },
    {
        "instruction": "Wrap all Stripe webhook handlers in idempotency checks using event.id.",
        "outcome": "Prevented duplicate subscription updates on Stripe retries.",
        "eval_score": 9.0,
        "tags": ["stripe", "billing"],
    },
]

_RECALL_PAYLOADS = [
    {"query": "async python patterns", "top_k": 3},
    {"query": "database migration strategy", "top_k": 3},
    {"query": "embedding cost optimisation", "top_k": 5},
    {"query": "stripe webhook idempotency", "top_k": 3},
    {"query": "API validation best practices", "top_k": 5},
    {"query": "zero-downtime deployment", "top_k": 3},
    {"query": "connection pool management", "top_k": 3},
]


class EngramiaUser(HttpUser):
    """Simulates a single concurrent API client."""

    wait_time = between(0.5, 2.0)  # seconds between requests per user

    def on_start(self) -> None:
        self.client.headers.update({"Authorization": f"Bearer {_API_KEY}"})

    @task(int(_LEARN_RATIO * 10))
    def learn(self) -> None:
        payload = random.choice(_LEARN_PAYLOADS)
        with self.client.post(
            "/v1/learn",
            json=payload,
            catch_response=True,
            name="/v1/learn",
        ) as resp:
            if resp.status_code not in (200, 201):
                resp.failure(f"learn returned {resp.status_code}: {resp.text[:200]}")

    @task(int((1 - _LEARN_RATIO) * 10))
    def recall(self) -> None:
        payload = random.choice(_RECALL_PAYLOADS)
        with self.client.post(
            "/v1/recall",
            json=payload,
            catch_response=True,
            name="/v1/recall",
        ) as resp:
            if resp.status_code not in (200, 201):
                resp.failure(f"recall returned {resp.status_code}: {resp.text[:200]}")

    @task(1)
    def health(self) -> None:
        with self.client.get(
            "/v1/health",
            catch_response=True,
            name="/v1/health",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"health returned {resp.status_code}")
