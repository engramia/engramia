# CLAUDE.md — Agent Brain

## Co je Agent Brain

Standalone Python knihovna a REST API pro **self-learning agent memory**.
Řeší problém, který má každý agent framework: agenti se neučí z předchozích běhů.

Agent Brain je extrakce nejhodnotnější části projektu Agent Factory V2 —
closed-loop learning systému, který se za 254 běhů naučil dosahovat 93% success rate.

## Problém

Existující agent frameworky (LangChain, CrewAI, AutoGPT) jsou statické:
- Vygeneruj agenta → spusť → zahoď
- Každý běh začíná od nuly
- Žádné učení z úspěchů ani selhání
- Žádné znovupoužití existujících agentů
- Prompt engineering je manuální

## Řešení

Agent Brain poskytuje **paměťovou vrstvu** pro libovolný agent framework:

1. **Learn** — Zaznamenej výsledek běhu (task, kód, eval score, output, feedback)
2. **Recall** — Najdi relevantní agenty/patterny pro nový task (semantic search + eval weighting)
3. **Compose** — Sestav multi-agent pipeline z existujících agentů (contract validation)
4. **Evaluate** — Multi-evaluator scoring s variance detection
5. **Improve** — Automatická feedback injection do promptů, prompt evolution, pattern aging

## Architektura

Implementovaný stav (Phase 0 + Phase 1 + Phase 2 + Phase 3 + Phase 4):

```
agent_brain/
├── __init__.py              # Brain class + exceptions (public facade)
├── brain.py                 # Brain implementation
├── types.py                 # Pydantic modely (Pattern, Match, EvalResult, Pipeline, ...)
├── _util.py                 # Shared utility (extract_json_from_llm, jaccard, reuse_tier, PATTERNS_PREFIX)
├── exceptions.py            # ✅ Custom exceptions (BrainError, ProviderError, ValidationError, StorageError) (Phase 4)
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
├── api/                     # ✅ Implementováno (Phase 2)
│   ├── app.py               # App factory (create_app), env var konfigurace
│   ├── routes.py            # POST /learn /recall /compose /evaluate /aging /feedback/decay, GET /feedback /metrics /health, DELETE /patterns/{key}
│   ├── auth.py              # Bearer token middleware (BRAIN_API_KEYS, per-request)
│   ├── deps.py              # Dependency injection (Brain singleton)
│   └── schemas.py           # Request/Response Pydantic modely
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
│   ├── langchain.py         # LangChain BrainCallback (auto-learn, auto-recall)
│   └── webhook.py           # Lightweight HTTP SDK client (urllib, no deps)
│
└── cli/                     # ✅ Implementováno (Phase 4)
    └── main.py              # Typer CLI — init, serve, status, recall, aging
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
- **Custom exceptions** — `BrainError` hierarchie: `ProviderError`, `ValidationError`, `StorageError`. REST API mapuje ProviderError na HTTP 501.
- **Export/Import** — JSONL-compatible backup a migrace patternů (`brain.export()` / `brain.import_data()`).
- **CLI** — Typer + Rich CLI (`agent-brain init/serve/status/recall/aging`).
- **Model routing** — Empirická analýza: najdi nejlevnější model, který dosahuje ≥90% kvality nejdražšího.

## Použití

### Jako Python knihovna

```python
from agent_brain import Brain
from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

brain = Brain(
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
from agent_brain import ProviderError, ValidationError
try:
    brain.evaluate(task, code)
except ProviderError:
    pass  # no LLM configured
```

### Jako LangChain plugin (Phase 3)

```python
from agent_brain.sdk.langchain import BrainCallback

callback = BrainCallback(brain, auto_learn=True, auto_recall=True)
chain = LLMChain(llm=llm, prompt=prompt, callbacks=[callback])
# Brain se automaticky učí z chain runs a recalluje relevantní kontext
```

### Jako REST API

```bash
# JSON storage (dev)
docker compose up

# PostgreSQL storage (prod)
BRAIN_STORAGE=postgres BRAIN_DATABASE_URL=postgresql://... docker compose up
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
| `roadmap.md` | Implementační roadmapa (5 fází) |
| `alembic.ini` | Alembic konfigurace pro DB migrace |
| `docker-compose.yml` | Brain API + volitelný pgvector stack |
| `Dockerfile` | Multi-stage build (builder + runtime) |
| `agent_brain/__init__.py` | Public API surface (Brain class + exceptions + `__version__`) |
| `agent_brain/exceptions.py` | Custom exceptions (BrainError, ProviderError, ValidationError, StorageError) |
| `agent_brain/brain.py` | Brain facade — wiring všech internal stores |
| `agent_brain/types.py` | Pydantic modely — Pattern, Match, EvalResult, Pipeline, Metrics, ... |
| `agent_brain/_util.py` | Shared utility: `extract_json_from_llm()`, `jaccard()`, `reuse_tier()`, `PATTERNS_PREFIX` |
| `agent_brain/providers/base.py` | ABC pro LLM, Embedding, Storage (vč. `search_similar()`) |
| `agent_brain/providers/openai.py` | OpenAI LLM + Embeddings (lazy import, retry, native batch) |
| `agent_brain/providers/json_storage.py` | JSON atomic storage + threading.Lock + cosine similarity |
| `agent_brain/providers/postgres.py` | PostgreSQL + pgvector (HNSW, connection pool) |
| `agent_brain/core/success_patterns.py` | Pattern storage, aging, reuse boost |
| `agent_brain/core/eval_store.py` | Eval history, eval-weighted multiplier |
| `agent_brain/core/eval_feedback.py` | Feedback clustering (Jaccard), decay, surfacing |
| `agent_brain/core/metrics.py` | Run metriky, rolling history |
| `agent_brain/reuse/matcher.py` | Semantic search + eval weighting |
| `agent_brain/reuse/composer.py` | Pipeline decomposition + contract validation |
| `agent_brain/reuse/contracts.py` | reads/writes chain validation + circular detection |
| `agent_brain/eval/evaluator.py` | MultiEvaluator (N concurrent runs, median, variance) |
| `agent_brain/api/app.py` | FastAPI app factory, env var konfigurace |
| `agent_brain/api/routes.py` | Všechny API endpointy |
| `agent_brain/api/auth.py` | Bearer token middleware |
| `agent_brain/api/schemas.py` | API request/response modely |
| `agent_brain/providers/anthropic.py` | Anthropic/Claude LLM (lazy import, retry) |
| `agent_brain/providers/local_embeddings.py` | sentence-transformers (no API key, 384-dim) |
| `agent_brain/core/skill_registry.py` | Capability-based pattern tagging |
| `agent_brain/evolution/prompt_evolver.py` | LLM-based prompt improvement + A/B testing |
| `agent_brain/evolution/failure_cluster.py` | Failure pattern clustering |
| `agent_brain/sdk/langchain.py` | LangChain BrainCallback (auto-learn, auto-recall) |
| `agent_brain/sdk/webhook.py` | Lightweight HTTP SDK client (urllib, no deps) |
| `agent_brain/db/models.py` | SQLAlchemy modely (brain_data + brain_embeddings) |
| `agent_brain/db/migrations/` | Alembic migrace (001_initial: schema + HNSW index) |
| `agent_brain/cli/main.py` | Typer CLI — init, serve, status, recall, aging |
