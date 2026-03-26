# CLAUDE.md — Remanence

## Co je Remanence

Standalone Python knihovna a REST API pro **self-learning agent memory**.
Řeší problém, který má každý agent framework: agenti se neučí z předchozích běhů.

Remanence je extrakce nejhodnotnější části projektu Agent Factory V2 —
closed-loop learning systému, který se za 254 běhů naučil dosahovat 93% success rate.

## Problém

Existující agent frameworky (LangChain, CrewAI, AutoGPT) jsou statické:
- Vygeneruj agenta → spusť → zahoď
- Každý běh začíná od nuly
- Žádné učení z úspěchů ani selhání
- Žádné znovupoužití existujících agentů
- Prompt engineering je manuální

## Řešení

Remanence poskytuje **paměťovou vrstvu** pro libovolný agent framework:

1. **Learn** — Zaznamenej výsledek běhu (task, kód, eval score, output, feedback)
2. **Recall** — Najdi relevantní agenty/patterny pro nový task (semantic search + eval weighting)
3. **Compose** — Sestav multi-agent pipeline z existujících agentů (contract validation)
4. **Evaluate** — Multi-evaluator scoring s variance detection
5. **Improve** — Automatická feedback injection do promptů, prompt evolution, pattern aging

## Architektura

Implementovaný stav (Phase 0–4.5, Phase 4.6 probíhá):

```
remanence/
├── __init__.py              # Brain class + exceptions (public facade)
├── brain.py                 # Brain implementation
├── types.py                 # Pydantic modely (Pattern, Match, EvalResult, Pipeline, ...)
├── _util.py                 # Shared utility (extract_json_from_llm, jaccard, reuse_tier, PATTERNS_PREFIX)
├── exceptions.py            # ✅ Custom exceptions (RemanenceError, ProviderError, ValidationError, StorageError) (Phase 4)
│
├── core/                    # ✅ Implementováno
│   ├── success_patterns.py  # Pattern storage, aging (2%/týden), reuse tracking (+0.1, max 10.0)
│   ├── eval_store.py        # Eval výsledky, eval-weighted multiplier [0.5, 1.0]
│   ├── eval_feedback.py     # Recurring feedback clustering (Jaccard >0.4, decay 10%/týden)
│   ├── metrics.py           # Run/success/failure/reuse metriky, rolling history 100
│   └── skill_registry.py    # ✅ Capability-based pattern tagging (Phase 3)
│
├── reuse/                   # ✅ Implementováno
│   ├── matcher.py           # Semantic search + eval weighting (fetch limit*3, re-sort)
│   ├── composer.py          # LLM pipeline decompose + PatternMatcher per stage + validation
│   └── contracts.py         # reads/writes chain validation + circular detection
│
├── eval/                    # ✅ Implementováno
│   └── evaluator.py         # MultiEvaluator (ThreadPoolExecutor, median, variance >1.5)
│
├── providers/               # ✅ OpenAI + Anthropic + Local + JSON + Postgres
│   ├── base.py              # ABC: LLMProvider, EmbeddingProvider, StorageBackend
│   ├── openai.py            # OpenAI LLM (retry 3x) + OpenAIEmbeddings (native batch)
│   ├── anthropic.py         # ✅ Anthropic/Claude LLM (retry, lazy import) (Phase 3)
│   ├── local_embeddings.py  # ✅ sentence-transformers (no API key) (Phase 3)
│   ├── json_storage.py      # JSON atomic writes, in-memory index, threading.Lock
│   └── postgres.py          # PostgreSQL + pgvector (SQLAlchemy, HNSW index)
│
├── api/                     # ✅ Implementováno (Phase 2 + Phase 4.5)
│   ├── app.py               # App factory (create_app), env var konfigurace
│   ├── routes.py            # POST /learn /recall /compose /evaluate /aging /feedback/decay, GET /feedback /metrics /health, DELETE /patterns/{key}
│   ├── auth.py              # Bearer token middleware (REMANENCE_API_KEYS, per-request)
│   ├── deps.py              # Dependency injection (Brain singleton)
│   ├── schemas.py           # Request/Response Pydantic modely
│   ├── audit.py             # Structured audit logging (AUTH_FAILURE, PATTERN_DELETED, RATE_LIMITED)
│   └── middleware.py        # SecurityHeadersMiddleware, RateLimitMiddleware, BodySizeLimitMiddleware
│
├── db/                      # ✅ Implementováno (Phase 2)
│   ├── models.py            # SQLAlchemy 2.x modely (BrainData, BrainEmbedding)
│   └── migrations/          # Alembic (env.py, script.py.mako, 001_initial.py)
│
├── evolution/               # ✅ Implementováno (Phase 3)
│   ├── prompt_evolver.py    # LLM-based prompt improvement + A/B testing
│   └── failure_cluster.py   # Failure pattern clustering (Jaccard-based)
│
├── sdk/                     # ✅ Implementováno (Phase 3)
│   ├── langchain.py         # LangChain RemanenceCallback (auto-learn, auto-recall)
│   └── webhook.py           # Lightweight HTTP SDK client (urllib, no deps)
│
├── cli/                     # ✅ Implementováno (Phase 4)
│   └── main.py              # Typer CLI — init, serve, status, recall, aging
│
└── mcp/                     # 🔲 Plánováno (Phase 4.6.9)
    └── server.py            # MCP server — Brain API jako MCP tools
```

### Provider abstrakce

Brain je **model-agnostic** a **storage-agnostic**:

- **LLM**: OpenAI, Anthropic, libovolný provider implementující `LLMProvider` ABC
- **Embeddings**: OpenAI (`text-embedding-3-small` jako default), lokální modely (sentence-transformers). Rozšiřitelné přes `EmbeddingProvider` ABC.
- **Storage**: JSON soubory (single-machine, thread-safe) nebo PostgreSQL + pgvector (SaaS). Storage abstrakce zahrnuje vector search (`search_similar(embedding, limit, prefix)`) — JSON backend dělá brute-force cosine similarity, Postgres využívá pgvector HNSW index.

### Klíčové koncepty

- **Success patterns** — Úspěšné agent designy s time-based decay (2%/týden). Automatické zapomínání zastaralého.
- **Eval feedback injection** — Recurring quality issues se automaticky injektují do coder promptu.
- **Contract validation** — Pipeline stages deklarují reads/writes. Brain validuje konzistenci data flow i cyklické závislosti.
- **Multi-eval scoring** — N nezávislých LLM evaluací, median agregace, variance detection (>1.5 = warning).
- **Semantic agent search** — Task-based embeddings pro přesné vyhledávání podobných agentů.
- **Pattern aging** — Staré patterny přirozeně klesají na skóre, nové je vytlačují.
- **Prompt evolution** — LLM generuje vylepšené prompty na základě recurring failure patterns; volitelné A/B testování.
- **Failure clustering** — Jaccard-based seskupení opakujících se chyb pro identifikaci systémových problémů.
- **Skill registry** — Explicitní capability tagging patternů; kombinuje s semantic search pro přesné matching.
- **Custom exceptions** — `RemanenceError` hierarchie: `ProviderError`, `ValidationError`, `StorageError`. REST API mapuje ProviderError na HTTP 501.
- **Security hardening** — OWASP ASVS Level 2/3: timing-safe auth (hmac.compare_digest), rate limiting (per-IP/path), security headers, CORS (disabled by default), body size limit, prompt injection delimiters, audit logging (structured JSON), Docker non-root user, API versioning /v1/. Error sanitization (no internal details in HTTP responses). Path traversal prevention (`..` rejection). LIKE wildcard escaping in PostgreSQL. See `SECURITY.md` for known limitations and production checklist.
- **Input validation** — eval_score [0,10], import_data/delete_pattern prefix check, num_evals cap, SHA-256 pro key generation, max_length on all API schema string fields.
- **Export/Import** — JSONL-compatible backup a migrace patternů (`brain.export()` / `brain.import_data()`).
- **CLI** — Typer + Rich CLI (`remanence init/serve/status/recall/aging`).
- **Model routing** — Empirická analýza: najdi nejlevnější model, který dosahuje ≥90% kvality nejdražšího.

### Plánované features (roadmap)

- **MCP Server** (Phase 4.6.9) — Brain API jako MCP tools pro Claude Desktop, Cursor, Windsurf.
- **Knowledge Graph** (Phase 6) — Entity/relationship vrstva nad patterny pro grafové dotazy a vizualizaci.
- **Memory taxonomie** (Phase 6) — Explicitní separace episodic (konkrétní běhy), semantic (fakta, entity), procedural (naučené dovednosti).
- **Memory compression** (Phase 6) — Shrnutí starých patternů místo pouhého score decay.
- **Multi-agent sharing** (Phase 6) — Sdílené pattern pools s access control a conflict resolution.
- **OpenTelemetry** (Phase 5) — Traces/spans pro observability stacky (Langfuse, Datadog, Grafana).
- **RBAC + SSO/SAML** (Phase 5) — Enterprise access control, per-team memory isolation.
- **GDPR compliance** (Phase 5) — Right to erasure, data residency, DPA.
- **Multimodal** (Phase 7) — Image/audio/video reference s textovými popisy.
- **Marketplace** (Phase 8) — Community pattern sharing a monetizace.

## Použití

### Jako Python knihovna

```python
from remanence import Memory
from remanence.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)

# Learn
brain.learn(task="Parse CSV and compute stats", code=code, eval_score=8.5, output=stdout)

# Recall — vrátí Match objekty s pattern_key pro případné smazání
matches = brain.recall(task="Read CSV and calculate averages", limit=5)

# Delete pattern
brain.delete_pattern(matches[0].pattern_key)

# Compose pipeline
pipeline = brain.compose(task="Fetch stock data, analyze, write report")

# Evaluate
result = brain.evaluate(task=task, code=code, output=stdout)

# Feedback for prompt injection
feedback = brain.get_feedback(task_type="csv", limit=4)

# Prompt evolution (Phase 3)
result = brain.evolve_prompt(role="coder", current_prompt="You are a coder...")

# Failure analysis (Phase 3)
clusters = brain.analyze_failures(min_count=2)

# Skill registry (Phase 3)
brain.register_skills(matches[0].pattern_key, ["csv_parsing", "statistics"])
results = brain.find_by_skills(["csv_parsing"])

# Export / Import (Phase 4)
records = brain.export()   # list[dict] — JSONL-compatible
imported = brain.import_data(records, overwrite=False)

# Custom exceptions (Phase 4)
from remanence import ProviderError, ValidationError
try:
    brain.evaluate(task, code)
except ProviderError:
    pass  # no LLM configured
```

### Jako LangChain plugin (Phase 3)

```python
from remanence.sdk.langchain import RemanenceCallback

callback = RemanenceCallback(brain, auto_learn=True, auto_recall=True)
chain = LLMChain(llm=llm, prompt=prompt, callbacks=[callback])
# Brain se automaticky učí z chain runs a recalluje relevantní kontext
```

### Jako REST API

```bash
# JSON storage (dev)
docker compose up

# PostgreSQL storage (prod)
REMANENCE_STORAGE=postgres REMANENCE_DATABASE_URL=postgresql://... docker compose up
```

```
POST /learn                 — zaznamenej výsledek běhu
POST /recall                — najdi relevantní agenty
POST /compose               — navrhni pipeline
POST /evaluate              — multi-eval scoring
POST /aging                 — spusť pattern aging (decay + prune)
POST /feedback/decay        — spusť feedback decay
POST /evolve                — vygeneruj vylepšený prompt (Phase 3)
POST /analyze-failures      — seskupí failure patterny (Phase 3)
POST /skills/register       — registruje skill tagy na pattern (Phase 3)
POST /skills/search         — vyhledá patterny dle skill tagů (Phase 3)
GET  /feedback              — top feedback patterns
GET  /metrics               — statistiky
GET  /health                — health check + storage type
DELETE /patterns/{key}      — smaž pattern
```

Swagger UI: `http://localhost:8000/docs`

## Původ

Extrahováno z Agent Factory V2 — self-improving AI agent factory.
Factory zůstává jako open-source referenční implementace, která dokazuje, že Brain funguje.

## Technologie

- Python 3.12+
- FastAPI + uvicorn (REST API)
- Typer + Rich (CLI)
- SQLAlchemy 2.x + pgvector (optional Postgres backend)
- Alembic (migrace)
- OpenAI / Anthropic SDK (provider-agnostic)
- Pydantic v2 (data validation)
- numpy (cosine similarity v JSON backend)

## Konvence

- Provider abstrakce přes ABC — každý nový provider implementuje base interface
- Storage je pluggable — JSON pro dev/single-machine, Postgres pro SaaS
- Žádné hardcoded API klíče — vše přes env vars nebo konstruktor
- Testy pro každý modul — pytest, fail_under=80%
- Type hints na všech public API
- Docstrings na public functions (Google style)
- `logging.getLogger(__name__)` v každém modulu — žádné print() v produkčním kódu
- Input validace na Brain API boundary (task/code délky, limit bounds, num_evals ≥ 1)

## Klíčové soubory

| Soubor | Účel |
|--------|------|
| `roadmap.md` | Implementační roadmapa (fáze 0–9 + security requirements) |
| `CHANGELOG.md` | Release notes pro všechny verze (Keep a Changelog formát) |
| `SECURITY.md` | Security policy, known limitations, production deployment checklist |
| `alembic.ini` | Alembic konfigurace pro DB migrace |
| `docker-compose.yml` | Brain API + volitelný pgvector stack |
| `Dockerfile` | Multi-stage build (builder + runtime) |
| `remanence/__init__.py` | Public API surface (Brain class + exceptions + `__version__`) |
| `remanence/exceptions.py` | Custom exceptions (RemanenceError, ProviderError, ValidationError, StorageError) |
| `remanence/brain.py` | Brain facade — wiring všech internal stores |
| `remanence/types.py` | Pydantic modely — Pattern, Match, EvalResult, Pipeline, Metrics, ... |
| `remanence/_util.py` | Shared utility: `extract_json_from_llm()`, `jaccard()`, `reuse_tier()`, `PATTERNS_PREFIX` |
| `remanence/providers/base.py` | ABC pro LLM, Embedding, Storage (vč. `search_similar()`) |
| `remanence/providers/openai.py` | OpenAI LLM + Embeddings (lazy import, retry, native batch) |
| `remanence/providers/json_storage.py` | JSON atomic storage + threading.Lock + cosine similarity |
| `remanence/providers/postgres.py` | PostgreSQL + pgvector (HNSW, connection pool) |
| `remanence/core/success_patterns.py` | Pattern storage, aging, reuse boost |
| `remanence/core/eval_store.py` | Eval history, eval-weighted multiplier |
| `remanence/core/eval_feedback.py` | Feedback clustering (Jaccard), decay, surfacing |
| `remanence/core/metrics.py` | Run metriky, rolling history |
| `remanence/reuse/matcher.py` | Semantic search + eval weighting |
| `remanence/reuse/composer.py` | Pipeline decomposition + contract validation |
| `remanence/reuse/contracts.py` | reads/writes chain validation + circular detection |
| `remanence/eval/evaluator.py` | MultiEvaluator (N concurrent runs, median, variance) |
| `remanence/api/app.py` | FastAPI app factory, env var konfigurace |
| `remanence/api/routes.py` | Všechny API endpointy |
| `remanence/api/auth.py` | Bearer token middleware |
| `remanence/api/schemas.py` | API request/response modely |
| `remanence/api/audit.py` | Structured audit logging (security events) |
| `remanence/api/middleware.py` | Security headers, rate limiting, body size limit middleware |
| `remanence/providers/anthropic.py` | Anthropic/Claude LLM (lazy import, retry) |
| `remanence/providers/local_embeddings.py` | sentence-transformers (no API key, 384-dim) |
| `remanence/core/skill_registry.py` | Capability-based pattern tagging |
| `remanence/evolution/prompt_evolver.py` | LLM-based prompt improvement + A/B testing |
| `remanence/evolution/failure_cluster.py` | Failure pattern clustering |
| `remanence/sdk/langchain.py` | LangChain RemanenceCallback (auto-learn, auto-recall) |
| `remanence/sdk/webhook.py` | Lightweight HTTP SDK client (urllib, no deps) |
| `remanence/db/models.py` | SQLAlchemy modely (brain_data + brain_embeddings) |
| `remanence/db/migrations/` | Alembic migrace (001_initial: schema + HNSW index) |
| `remanence/cli/main.py` | Typer CLI — init, serve, status, recall, aging |
