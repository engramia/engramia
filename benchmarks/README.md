# Engramia Benchmark Suite

Three benchmark surfaces, each measuring a different aspect of
Engramia's behaviour:

1. **[LongMemEval](LONGMEMEVAL.md)** — semantic recall quality on a
   500-task synthetic suite plus an Oracle port of the Wu 2024
   real-dataset benchmark. Covers single_hop / multi_hop /
   temporal / knowledge_updates / absent_memory_detection.
2. **[AgentLifecycleBench](LIFECYCLE.md)** — closed-loop memory
   scenarios: improvement curve, deprecation speed, conflict
   resolution, concept drift, noise rejection. Runs against
   Engramia, Mem0, and Hindsight through the same adapter
   protocol; competitors return `capability_missing` on every
   scenario because they don't expose a refinement write path.
3. **Legacy 254-task Agent Factory V2 bench** (documented below) —
   pre-audit harness quoted as "93 % task success rate" in earlier
   marketing copy. Retained as a reproducible reference, but the
   93 % number pre-dates the 2026-04-21 methodology audit and
   should not be cited without the caveat.

---

## Legacy 254-task Agent Factory V2 bench

Reproducible benchmark that validated an earlier milestone — the
**93 % task success rate** observed in Agent Factory V2 (254 runs).
All numbers below pre-date the 2026-04-21 methodology audit. For
current public claims, prefer AgentLifecycleBench medium-difficulty
numbers and the post-audit LongMemEval columns.

## What this benchmark proves

Engramia improves agent success rates by giving agents access to relevant,
high-quality patterns from previous runs. This benchmark independently measures
the two components that drive that improvement:

1. **Recall precision** — when a relevant pattern exists in memory, does
   `recall()` find it?
2. **Quality ranking** — when multiple patterns match, does the best one
   rank first?

## Methodology

### Dataset

254 tasks across 12 realistic agent domains:

| Domain | Description |
|--------|-------------|
| Code generation | REST endpoints, service classes, CLI tools |
| Bug diagnosis | Root-cause analysis, targeted fixes |
| Test generation | pytest suites, fixtures, mocking, edge cases |
| Refactoring | Service extraction, separation of concerns |
| Data pipeline | ETL: S3 ingestion, transformation, Postgres load |
| API integration | Stripe/Twilio with retry, idempotency, webhooks |
| Infrastructure | Terraform modules, ECS Fargate, auto-scaling |
| Database migration | Alembic, schema splits, data backfill |
| Security hardening | Rate limiting, CSRF, input sanitization |
| Documentation | OpenAPI specs, developer guides, error catalogs |
| Performance | N+1 query fixes, eager loading, caching |
| CI/CD | GitHub Actions, Docker builds, staging deploy |

Task composition:
- **210 in-domain** — 5 variants per domain + paraphrases
- **30 boundary** — cross-domain tasks (e.g. "test the ETL pipeline")
- **14 noise** — completely unrelated (image processing, games, hardware)

Each domain has **3 code quality tiers** (good / medium / bad) with realistic
agent-generated code, scored 2.0–9.3.

### Scenarios

| Scenario | Training patterns | What it proves |
|----------|-------------------|----------------|
| **Cold start** | 0 | Baseline — memory adds zero value |
| **Warm-up** | 12 (1 per domain) | Memory helps immediately |
| **Full library** | 36 (3 per domain) | Steady-state — the 93% regime |

### Success criteria

A task **succeeds** if:
- **In-domain/boundary**: top-1 recall has similarity above the
  auto-calibrated threshold AND is from the correct domain
- **Noise**: no match above the noise threshold (correctly rejected)

### Auto-calibration

Similarity thresholds vary by embedding model (OpenAI 1536-dim vs local
384-dim produce different cosine ranges). The benchmark auto-calibrates
by computing intra-domain vs cross-domain similarities at startup and
setting the threshold to separate them. This makes results reproducible
across embedding models without manual tuning.

### Reproducibility

- Uses `all-MiniLM-L6-v2` embeddings (local, no API key)
- Auto-calibrated thresholds (no hardcoded values)
- Temporary JSON storage (auto-cleaned)
- Deterministic given the same embedding model
- No LLM calls in the benchmark path

## How to run

```bash
# Install local embeddings
pip install engramia[local]

# Run all scenarios
python -m benchmarks

# Run specific scenario
python -m benchmarks --scenario full

# Validate dataset integrity
python -m benchmarks --validate

# Purge previous results
python -m benchmarks --clean

# Keep temp storage for inspection
python -m benchmarks --keep

# Verbose logging
python -m benchmarks -v
```

## Output

### Terminal (actual results with all-MiniLM-L6-v2)

```
========================================================================
  BENCHMARK SUMMARY
========================================================================
  Scenario           Patterns    Success     Rate      P@1     Time
  ------------------ -------- ---------- -------- -------- --------
  cold_start                0     14/254     5.5%     0.0%     3.7s
  warm_up                  12    205/218    94.0%    94.6%     7.8s
  full_library             36    251/254    98.8%    98.8%    10.7s
========================================================================
```

The progression from 5.5% (no memory) to 94% (12 patterns) to 98.8%
(36 patterns) demonstrates the core value proposition:
**memory-assisted agents succeed at dramatically higher rates.**

### JSON

Results are saved to `benchmarks/results/{timestamp}_{commit}.json` for
longitudinal tracking. Each file contains per-scenario metrics, git metadata,
and embedding model info.

## Exit codes

- `0` — full_library success rate ≥ 90%
- `1` — below threshold or validation failure

## Architecture

```
benchmarks/
├── __main__.py     # CLI entry point
├── dataset.py      # 254 tasks, 12 domains, ground truth labels
├── runner.py       # BenchmarkRunner — learn, recall, score
├── report.py       # Terminal output + JSON persistence
├── snippets/       # Code quality tiers per domain (good/medium/bad)
│   ├── a01_code_generation.py
│   ├── ...
│   └── a12_cicd_deployment.py
└── results/        # Timestamped JSON run files
```
