# Changelog

All notable changes to Remanence are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.5.0] — 2026-03-22

### Added — Security hardening (Phase 4.5)
- OWASP ASVS Level 2/3 compliance: timing-safe auth, rate limiting, security headers, body size limit, audit logging
- Prompt injection mitigation with XML delimiters in all LLM prompt templates
- API versioning — all endpoints under `/v1/` prefix
- Docker non-root user (`brain:1001`)
- `SECURITY.md` with 10 documented limitations and production deployment checklist

### Changed
- CORS disabled by default (was `*`); must be explicitly set via `REMANENCE_CORS_ORIGINS`
- SHA-256 replaces MD5 for all internal key generation
- HTTP error responses no longer expose internal exception details
- Audit logging uses structured JSON format

### Fixed
- Path traversal via `patterns/../...` keys now rejected
- PostgreSQL LIKE queries escape `%` and `_` wildcards
- API key count no longer leaked in startup log

---

## [0.4.0] — 2026-03-22

### Added — CLI, exceptions, export/import (Phase 4)
- CLI tool (`remanence init/serve/status/recall/aging`) via Typer + Rich
- Custom exception hierarchy: `RemanenceError`, `ProviderError`, `ValidationError`, `StorageError`
- `brain.export()` / `brain.import_data()` for JSONL-compatible backup and migration
- REST endpoints for Phase 3 features: `/evolve`, `/analyze-failures`, `/skills/register`, `/skills/search`

### Fixed
- `mark_reused()` now correctly updates pattern data
- Aging threshold comparison fixed
- Feedback length validation
- ISO timestamp parsing edge cases
- `ProviderError` mapped to HTTP 501

---

## [0.3.0] — 2026-03-22

### Added — SDK plugins, prompt evolution, skill registry (Phase 3)
- LangChain `RemanenceCallback` — auto-learn from chain runs, auto-recall context
- Webhook SDK client (`RemanenceWebhook`) — lightweight HTTP client (stdlib only)
- Anthropic/Claude LLM provider with retry and lazy import
- Local embeddings provider (sentence-transformers, no API key required)
- Prompt evolution — LLM-based prompt improvement with optional A/B testing
- Failure clustering — Jaccard-based grouping of recurring errors
- Skill registry — capability-based pattern tagging and search

### Changed
- Auth middleware reads env vars per-request (not at import time)
- Shared utilities extracted to `_util.py` (Jaccard, reuse_tier, PATTERNS_PREFIX)

### Fixed
- Duplicate import in routes.py
- `Brain.storage_type` property for health endpoint
- Generic error message in `_require_llm()`
- `.bak`/`.tmp` cleanup in `JSONStorage.delete()`

---

## [0.2.0] — 2026-03-22

### Added — REST API, PostgreSQL, Docker (Phase 2)
- FastAPI REST API with 14 endpoints (learn, recall, compose, evaluate, feedback, metrics, health, delete, aging, feedback/decay)
- Bearer token authentication via `REMANENCE_API_KEYS` env var
- PostgreSQL + pgvector storage backend with HNSW index
- Alembic migrations for database schema
- Docker multi-stage build + docker-compose
- OpenAPI/Swagger documentation at `/docs`

### Changed
- Input validation on Brain API boundary (task/code lengths, limit bounds)
- Thread safety in JSONStorage via `threading.Lock`

### Fixed
- Evaluator `num_evals` parameter handling
- Future timestamp edge cases
- Malformed ISO date parsing
- Circular pipeline detection in contract validation
- Embedding dimension mismatch error handling

---

## [0.1.0] — 2026-03-22

### Added — Core Brain library (Phase 0 + Phase 1)
- `Brain` class — central facade for self-learning agent memory
- `brain.learn()` — record successful agent runs as reusable patterns
- `brain.recall()` — semantic search with deduplication and eval-weighted matching
- `brain.evaluate()` — multi-evaluator scoring (N concurrent LLM runs, median, variance detection)
- `brain.compose()` — multi-agent pipeline composition with contract validation
- `brain.get_feedback()` — recurring quality issue surfacing for prompt injection
- `brain.run_aging()` — time-based pattern decay (2%/week) with auto-pruning
- Provider abstraction: `LLMProvider`, `EmbeddingProvider`, `StorageBackend` ABCs
- OpenAI LLM provider with retry
- OpenAI embeddings provider with native batch encoding
- JSON file storage with atomic writes and cosine similarity search
- Success pattern store with aging and reuse tracking
- Eval store with quality-weighted multiplier
- Feedback clustering (Jaccard > 0.4) with decay
- Metrics store (runs, success rate, avg score, reuse rate)
