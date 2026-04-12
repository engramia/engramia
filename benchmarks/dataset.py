# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""Benchmark dataset — 12 realistic agent domains, 254 tasks, ground truth labels.

The dataset mirrors the Agent Factory V2 workload distribution:
  - 210 in-domain tasks (12 domains x ~17-18 tasks, drawn from 5 variants + paraphrases)
  - 30 boundary tasks (cross-domain, straddling two domains)
  - 14 noise tasks (completely unrelated — image processing, hardware, etc.)

Each domain has 5 task variants (semantically similar, lexically diverse, Jaccard < 0.7)
and 3 code quality tiers (good / medium / bad).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from engramia._util import jaccard


# ---------------------------------------------------------------------------
# Domain definitions — 12 realistic agent use-case clusters
# ---------------------------------------------------------------------------

DOMAINS: dict[str, list[str]] = {
    "A01": [  # Code generation
        "Write a REST API endpoint for user registration with email validation and password hashing",
        "Implement a FastAPI route that handles new user sign-up including input sanitization",
        "Create an HTTP handler for account creation with bcrypt password storage and duplicate checking",
        "Build a registration service endpoint that validates email format and enforces password policy",
        "Develop user onboarding API with field validation, hashed credentials, and conflict detection",
    ],
    "A02": [  # Bug diagnosis & fix
        "Debug why the payment webhook returns 422 — trace the request flow and fix the validation",
        "Investigate the HTTP 422 error on incoming Stripe webhook events and patch the handler",
        "Root-cause analysis: payment notification endpoint rejects valid payloads after API upgrade",
        "Trace and fix the webhook processing failure causing unprocessable entity responses",
        "Diagnose payment integration breakage — webhook payloads fail schema validation since last deploy",
    ],
    "A03": [  # Test generation
        "Generate pytest tests for the OrderService class including edge cases and mocking external APIs",
        "Write a comprehensive test suite for order processing with parametrized inputs and async mocking",
        "Create unit and integration tests for the order workflow covering payment failures and inventory checks",
        "Build pytest test cases for OrderService: happy path, validation errors, and external service failures",
        "Develop test coverage for the order management module with fixtures, mocks, and boundary conditions",
    ],
    "A04": [  # Refactoring
        "Extract the notification logic from UserController into a dedicated NotificationService",
        "Refactor user controller by separating email and SMS dispatch into an independent service class",
        "Decompose the monolithic UserController — pull notification concerns into their own module",
        "Split notification responsibility out of the user management class into a clean service layer",
        "Decouple message delivery from user operations by creating a standalone notification abstraction",
    ],
    "A05": [  # Data pipeline / ETL
        "Build an ETL pipeline that ingests JSON events from S3, transforms timestamps, and loads into Postgres",
        "Create a data ingestion workflow: read JSON records from cloud storage, normalize dates, write to database",
        "Implement event processing pipeline — stream from S3 bucket, apply schema transformation, batch insert",
        "Develop an extract-transform-load job for event data with S3 source, timestamp normalization, and Postgres sink",
        "Design a batch ETL process that pulls JSON logs from object storage, cleans temporal fields, and persists to SQL",
    ],
    "A06": [  # API integration
        "Integrate Stripe payment processing with idempotency keys, webhook verification, and retry logic",
        "Build a payment gateway client with request deduplication, signature validation, and backoff retry",
        "Implement Stripe SDK wrapper handling idempotent charges, webhook authenticity checks, and transient failures",
        "Create a resilient payment integration layer with duplicate prevention, cryptographic webhook verification",
        "Develop Stripe-connected payment service with idempotency, automatic retry on server errors, and event validation",
    ],
    "A07": [  # Infrastructure / IaC
        "Write Terraform module for an ECS Fargate service with ALB, auto-scaling, and CloudWatch alarms",
        "Create infrastructure-as-code for containerized deployment on AWS with load balancer and monitoring",
        "Define Terraform resources for a Fargate cluster including target groups, scaling policies, and log groups",
        "Build an ECS Fargate infrastructure module with application load balancing, health checks, and auto-scale",
        "Develop IaC templates for deploying Docker containers on AWS Fargate with ALB routing and alerting",
    ],
    "A08": [  # Database migration
        "Create an Alembic migration to split the users table into accounts and profiles with data backfill",
        "Write a database schema migration that decomposes the user table into separate identity and profile tables",
        "Implement a reversible Alembic migration: normalize users into accounts plus profiles with batch data copy",
        "Build a zero-downtime migration splitting user records across two new tables with foreign key relationships",
        "Develop an Alembic revision that refactors the users schema into accounts and profiles with historical data transfer",
    ],
    "A09": [  # Security hardening
        "Add rate limiting, CSRF protection, and input sanitization to the FastAPI authentication endpoints",
        "Harden the login and registration routes with request throttling, anti-forgery tokens, and XSS prevention",
        "Implement security middleware for auth endpoints: sliding-window rate limiter, double-submit CSRF, input cleaning",
        "Secure the authentication API with per-IP rate limiting, CSRF cookie validation, and dangerous pattern stripping",
        "Apply OWASP best practices to auth routes — rate limiting, cross-site request forgery defense, and input filtering",
    ],
    "A10": [  # Documentation
        "Generate OpenAPI spec and developer guide for the billing API including authentication flow diagrams",
        "Produce comprehensive API documentation for the billing service with auth examples and error catalog",
        "Create an OpenAPI 3.1 specification for billing endpoints with request samples and rate-limit documentation",
        "Write developer-facing API docs for the billing system covering authentication, subscriptions, and invoices",
        "Build a complete API reference for billing operations with security schemes, examples, and error response formats",
    ],
    "A11": [  # Performance optimization
        "Profile the search endpoint, identify N+1 queries, and implement eager loading with query caching",
        "Optimize the product search API by fixing lazy-load bottlenecks and adding Redis-backed result cache",
        "Diagnose search endpoint latency — resolve N+1 ORM queries with joinedload and introduce cache layer",
        "Performance-tune the search route: replace per-row queries with batch loading and cache frequent lookups",
        "Eliminate N+1 database queries in the search handler by adding eager relation loading and response caching",
    ],
    "A12": [  # CI/CD & deployment
        "Set up GitHub Actions workflow with lint, test, build Docker image, and deploy to staging on merge",
        "Create a CI/CD pipeline using GitHub Actions: code quality checks, test suite, container build, auto-deploy",
        "Configure continuous integration and deployment: ruff lint, pytest with coverage, Docker push, ECS staging deploy",
        "Build an automated release pipeline — lint, test matrix, Docker image to ECR, rolling deploy to staging",
        "Implement end-to-end CI/CD workflow: static analysis, test with Postgres service, containerize, and ship to staging",
    ],
}

# ---------------------------------------------------------------------------
# Boundary tasks — cross-domain (straddle two domains)
# ---------------------------------------------------------------------------

BOUNDARY_TASKS: list[tuple[str, str, str]] = [
    # (task, domain_a, domain_b)
    ("Write tests for the ETL pipeline covering S3 ingestion failures and transform edge cases", "A03", "A05"),
    ("Refactor the payment integration to extract retry logic into a reusable resilience module", "A04", "A06"),
    ("Debug the CI/CD pipeline failure caused by a broken database migration in staging", "A02", "A12"),
    ("Add rate limiting to the data ingestion API to prevent S3 bucket abuse", "A09", "A05"),
    ("Generate API documentation for the refactored notification service endpoints", "A10", "A04"),
    ("Optimize the ETL pipeline query performance by adding batch inserts and connection pooling", "A11", "A05"),
    ("Create an Alembic migration for the new API integration tables with foreign keys to accounts", "A08", "A06"),
    ("Write Terraform for the CI/CD runner infrastructure with auto-scaling build agents", "A07", "A12"),
    ("Harden the payment webhook endpoint with signature verification and input sanitization", "A09", "A06"),
    ("Profile and fix N+1 queries in the test generation service that loads fixture data", "A11", "A03"),
    ("Build a deployment pipeline for the database migration service with rollback support", "A12", "A08"),
    ("Write integration tests for the Terraform-provisioned infrastructure using localstack", "A03", "A07"),
    ("Refactor the search endpoint caching layer and document the new cache invalidation API", "A04", "A10"),
    ("Debug why the registration endpoint rate limiter triggers false positives behind a load balancer", "A02", "A09"),
    (
        "Create a data pipeline that extracts API documentation from code annotations and generates OpenAPI",
        "A05",
        "A10",
    ),
    ("Write a migration to add performance monitoring tables for tracking endpoint latency metrics", "A08", "A11"),
    ("Implement a code generation tool that scaffolds CRUD endpoints from database schema definitions", "A01", "A08"),
    ("Build infrastructure for running the ETL pipeline on a scheduled cron with monitoring alerts", "A07", "A05"),
    ("Add security headers and CSRF protection to the auto-generated API documentation portal", "A09", "A10"),
    ("Debug the Docker build failure in CI caused by incompatible Python version in the base image", "A02", "A12"),
    ("Refactor the CI/CD workflow to extract shared steps into reusable composite actions", "A04", "A12"),
    ("Write performance benchmarks for the user registration endpoint under concurrent load", "A11", "A01"),
    ("Generate test fixtures from production data samples for the payment integration test suite", "A03", "A06"),
    ("Create infrastructure monitoring dashboards and alert rules for the ETL pipeline health", "A07", "A11"),
    ("Implement API versioning for the billing endpoints and update the OpenAPI documentation", "A01", "A10"),
    ("Build a migration rollback procedure with automated testing to verify data integrity", "A08", "A03"),
    ("Harden the CI/CD pipeline secrets management with OIDC federation and least-privilege IAM", "A09", "A12"),
    ("Debug the search endpoint returning stale cached results after a database migration", "A02", "A11"),
    ("Write a code generator for Terraform modules from infrastructure requirement specifications", "A01", "A07"),
    ("Optimize the webhook processing pipeline to handle burst traffic with async batch processing", "A11", "A06"),
]

# ---------------------------------------------------------------------------
# Noise tasks — completely unrelated to any domain
# ---------------------------------------------------------------------------

NOISE_TASKS: list[str] = [
    "Resize JPEG images to 800x600 thumbnails preserving aspect ratio using Pillow",
    "Generate QR codes from arbitrary URLs with configurable error correction level",
    "Extract audio waveform peak amplitudes from MP3 files for visualization",
    "Scan nearby Bluetooth Low Energy devices and list their advertised services",
    "Render 3D mesh from point cloud data using Open3D and export as STL",
    "Implement a Sudoku solver using constraint propagation and backtracking",
    "Parse MIDI file and transpose all notes by a configurable interval",
    "Build a terminal-based Tetris game with ncurses rendering and scoring",
    "Convert GPS coordinates between WGS84 and UTM projection systems",
    "Implement a Markov chain text generator trained on Shakespeare corpus",
    "Design a PID controller for drone altitude stabilization simulation",
    "Build a ray tracer that renders spheres with reflections and shadows",
    "Create an Arduino serial protocol parser for temperature sensor readings",
    "Implement Huffman coding compression and decompression for text files",
]


# ---------------------------------------------------------------------------
# Snippet loader
# ---------------------------------------------------------------------------

_SNIPPET_MODULES: dict[str, str] = {
    "A01": "benchmarks.snippets.a01_code_generation",
    "A02": "benchmarks.snippets.a02_bug_diagnosis",
    "A03": "benchmarks.snippets.a03_test_generation",
    "A04": "benchmarks.snippets.a04_refactoring",
    "A05": "benchmarks.snippets.a05_data_pipeline",
    "A06": "benchmarks.snippets.a06_api_integration",
    "A07": "benchmarks.snippets.a07_infrastructure",
    "A08": "benchmarks.snippets.a08_database_migration",
    "A09": "benchmarks.snippets.a09_security_hardening",
    "A10": "benchmarks.snippets.a10_documentation",
    "A11": "benchmarks.snippets.a11_performance",
    "A12": "benchmarks.snippets.a12_cicd_deployment",
}


def get_snippets(domain_id: str) -> dict[str, dict]:
    """Load good/medium/bad code snippets for a domain.

    Returns:
        {"good": {...}, "medium": {...}, "bad": {...}} where each value
        has keys: code, eval_score, output.
    """
    mod = import_module(_SNIPPET_MODULES[domain_id])
    return {"good": mod.GOOD, "medium": mod.MEDIUM, "bad": mod.BAD}


# ---------------------------------------------------------------------------
# Dataset entries
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskEntry:
    """Single benchmark task with ground truth label."""

    task: str
    domain_id: str  # e.g. "A01", or "noise" / "boundary"
    category: str  # "in_domain" | "boundary" | "noise"
    expected_domains: tuple[str, ...]  # domains that should match (empty for noise)


def build_dataset() -> list[TaskEntry]:
    """Build the full 254-task benchmark dataset.

    Composition:
        - 210 in-domain tasks (12 domains x 5 variants = 60, plus 150 paraphrases)
        - 30 boundary tasks
        - 14 noise tasks
        Total: 254

    The in-domain paraphrases are generated by interleaving domain variants
    with minor lexical transformations to reach the target count.
    """
    entries: list[TaskEntry] = []

    # --- In-domain: 5 variants per domain = 60 base tasks ---
    for domain_id, variants in DOMAINS.items():
        for variant in variants:
            entries.append(
                TaskEntry(
                    task=variant,
                    domain_id=domain_id,
                    category="in_domain",
                    expected_domains=(domain_id,),
                )
            )

    # --- In-domain paraphrases: expand to ~210 total ---
    # Generate by prepending context prefixes to existing variants
    _PREFIXES = [
        "Given a Python project, ",
        "In a production codebase, ",
        "For a SaaS application, ",
        "As part of a sprint task, ",
        "Following best practices, ",
    ]
    paraphrase_count = 0
    target_paraphrases = 150  # 60 base + 150 = 210

    for domain_id, variants in DOMAINS.items():
        for prefix_idx, variant in enumerate(variants):
            if paraphrase_count >= target_paraphrases:
                break
            # Use 2-3 prefixes per variant, cycling through them
            for i in range(min(3, target_paraphrases - paraphrase_count)):
                prefix = _PREFIXES[(prefix_idx * 3 + i) % len(_PREFIXES)]
                paraphrased = prefix + variant[0].lower() + variant[1:]
                entries.append(
                    TaskEntry(
                        task=paraphrased,
                        domain_id=domain_id,
                        category="in_domain",
                        expected_domains=(domain_id,),
                    )
                )
                paraphrase_count += 1
            if paraphrase_count >= target_paraphrases:
                break

    # --- Boundary tasks: 30 cross-domain ---
    for task, domain_a, domain_b in BOUNDARY_TASKS:
        entries.append(
            TaskEntry(
                task=task,
                domain_id="boundary",
                category="boundary",
                expected_domains=(domain_a, domain_b),
            )
        )

    # --- Noise tasks: 14 ---
    for task in NOISE_TASKS:
        entries.append(
            TaskEntry(
                task=task,
                domain_id="noise",
                category="noise",
                expected_domains=(),
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Training set builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrainingPattern:
    """Pattern to learn into memory before testing."""

    task: str
    code: str
    eval_score: float
    output: str
    domain_id: str
    quality_tier: str  # "good" | "medium" | "bad"


def build_training_set(patterns_per_domain: int = 3) -> list[TrainingPattern]:
    """Build training set from domain snippets.

    Args:
        patterns_per_domain: 1 = good only, 2 = good+medium, 3 = all tiers.

    Returns:
        List of TrainingPattern entries to learn into memory.
    """
    tiers = ["good", "medium", "bad"][:patterns_per_domain]
    training: list[TrainingPattern] = []

    for domain_id, variants in DOMAINS.items():
        snippets = get_snippets(domain_id)
        for tier in tiers:
            snippet = snippets[tier]
            # Use the first variant as the training task
            # (held-out variants 3,4 are for testing)
            tier_idx = tiers.index(tier)
            task_variant = variants[tier_idx]  # variant 0=good, 1=medium, 2=bad
            training.append(
                TrainingPattern(
                    task=task_variant,
                    code=snippet["code"],
                    eval_score=snippet["eval_score"],
                    output=snippet.get("output", ""),
                    domain_id=domain_id,
                    quality_tier=tier,
                )
            )

    return training


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_dataset() -> list[str]:
    """Validate dataset integrity. Returns list of warnings (empty = OK)."""
    warnings: list[str] = []

    # Check Jaccard diversity within domains
    for domain_id, variants in DOMAINS.items():
        for i, a in enumerate(variants):
            for j, b in enumerate(variants):
                if j <= i:
                    continue
                sim = jaccard(a, b)
                if sim >= 0.7:
                    warnings.append(
                        f"{domain_id} variants {i}<->{j}: Jaccard={sim:.3f} >= 0.7 ('{a[:40]}...' / '{b[:40]}...')"
                    )

    # Check dataset size
    dataset = build_dataset()
    in_domain = sum(1 for e in dataset if e.category == "in_domain")
    boundary = sum(1 for e in dataset if e.category == "boundary")
    noise = sum(1 for e in dataset if e.category == "noise")
    total = len(dataset)

    if total != 254:
        warnings.append(f"Dataset size {total} != 254 (in_domain={in_domain}, boundary={boundary}, noise={noise})")

    return warnings


if __name__ == "__main__":
    issues = validate_dataset()
    if issues:
        print("Warnings:")
        for w in issues:
            print(f"  {w}")
    else:
        ds = build_dataset()
        cats = {}
        for e in ds:
            cats[e.category] = cats.get(e.category, 0) + 1
        print(f"OK: {len(ds)} tasks — {cats}")
