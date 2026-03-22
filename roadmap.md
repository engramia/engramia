# Agent Brain — Roadmap

## Vize

Vytvořit standalone Python knihovnu + REST API pro **self-learning agent memory**.
Produkt, který dá libovolnému agent frameworku (LangChain, CrewAI, AutoGPT, custom)
schopnost učit se z každého běhu — pamatovat si co funguje, zapomínat co nefunguje,
znovupoužívat ověřené agenty a automaticky zlepšovat kvalitu promptů.

Extrahujeme nejhodnotnější IP z Agent Factory V2 a balíme ji jako generický,
model-agnostic a storage-agnostic produkt.

---

## Konkurenční analýza

### Kde máme výhodu

| Oblast | My (Agent Brain) | LangChain/LangSmith | CrewAI | AutoGPT |
|--------|-------------------|---------------------|--------|---------|
| **Closed-loop learning** | ✅ Pattern aging, feedback injection, prompt evolution | ❌ Tracing only (observability, ne learning) | ❌ Žádné | ❌ Žádné |
| **Agent reuse** | ✅ Semantic search + eval-weighted matching + contract validation | ❌ Manuální | ❌ Manuální | ❌ Žádné |
| **Pipeline composition** | ✅ Automatická s contract validation (reads/writes) | ⚠️ LCEL chains (manuální) | ⚠️ Crew config (manuální) | ❌ |
| **Multi-evaluator scoring** | ✅ N runs, median, variance detection, adversarial check | ❌ | ❌ | ❌ |
| **Model routing** | ✅ Empirické — data-driven, per-role, per-task-type | ❌ | ❌ | ❌ |
| **Pattern aging** | ✅ Time-decay, staré patterny přirozeně mizí | ❌ | ❌ | ❌ |
| **Framework-agnostic** | ✅ Knihovna, REST API, SDK pluginy | ❌ LangChain-only | ❌ CrewAI-only | ❌ |

### Kde nemáme výhodu (a nesnažíme se)

- **Orchestrace agentů** — to dělá LangChain/CrewAI, my jsme paměť pod nimi
- **Sandboxing** — to zůstává v Agent Factory (nebo jiném hosteru)
- **UI/Dashboard** — Tier 2 priorita, ne core produkt
- **Marketplace** — až po ověření PMF

### Proč "Brain" místo "Factory"

Factory = end-to-end systém (generace + sandbox + security + learning).
Brain = jen learning vrstva, pluggable do čehokoli.

**Menší scope = větší adoption:**
- LangChain vývojář přidá Brain jako callback, nemusí migrovat orchestraci
- CrewAI tým přidá Brain jako middleware, crew workflow zůstane
- Custom framework dostane self-learning zadarmo

---

## Monetizace

### Model: Open-core + SaaS

| Tier | Obsah | Cena |
|------|-------|------|
| **Free (nekomerční)** | Core knihovna (patterns, eval, reuse, aging). JSON storage. CLI. Evaluace, výzkum, osobní projekty. | Zdarma |
| **Cloud** | Hosted REST API, PostgreSQL + pgvector backend, dashboard, team sharing. Komerční použití. | $49-199/měsíc |
| **Enterprise (on-prem)** | Self-hosted licence, SSO, audit log, SLA, custom integrations, dedicated support | Custom |

### Revenue drivers

1. **Storage & compute** — Embeddings, multi-eval LLM calls, pgvector search
2. **Team features** — Sdílená brain instance, RBAC, audit trail
3. **Framework pluginy** — Premium integrace (LangChain, CrewAI, Autogen)
4. **Model routing savings** — Brain ušetří na LLM nákladech → upsell na "platíš méně za LLM, zaplať nám"

### Go-to-market

1. **Dev-first** — Kvalitní open-source knihovna, dobrá dokumentace, pip install
2. **Content** — Blog posty: "How we achieved 93% success rate with self-learning agents"
3. **Integration** — LangChain/CrewAI pluginy jako entry point
4. **Community** — Discord, GitHub Discussions
5. **Enterprise** — Outbound až po ověření PMF na Cloud tier

---

## Fáze implementace

### Fáze 0: Skeleton
> Cíl: Fungující projekt s provider abstrakcí a jedním end-to-end testem.

- [x] Inicializace projektu (pyproject.toml, pytest, CI)
- [x] Provider ABC definice:
  - `LLMProvider` — `call(prompt, system, role) -> str`
  - `EmbeddingProvider` — `embed(text) -> list[float]`
  - `StorageBackend` — `load(key) -> dict`, `save(key, data)`, `list_keys() -> list[str]`, `search_similar(embedding, limit) -> list[tuple[str, float]]`
- [x] `OpenAIProvider` implementace (extrakce z agent_factory_v2/utils/llm_client.py)
- [x] `OpenAIEmbeddings` implementace (extrakce z agent_factory_v2/memory/agent_embeddings.py)
- [x] `JSONStorage` implementace (extrakce atomic write patternu z agent_factory_v2)
- [x] `Brain` třída — minimální facade:
  - `brain.learn(task, code, score)` → uloží success pattern
  - `brain.recall(task, limit, deduplicate) -> list[Match]` → semantic search s dedup groupingem (Jaccard > 0.7 = same task, vrací top-scoring per group)
- [x] Jeden end-to-end test: learn → recall → assert match (vč. dedup testy)
- [x] README.md s quick-start příkladem

**Deliverable:** `pip install -e .` funguje, learn/recall funguje s OpenAI embeddings + JSON storage.

---

### Fáze 1: Core Brain
> Cíl: Plný learning cyklus — learn, recall, evaluate, compose, improve.

- [x] **Success patterns** modul — aging (2%/týden), reuse tracking (+0.1 boost, max 10.0)
- [x] **Eval store** modul — rolling window 200, eval-weighted multiplier [0.5, 1.0]
- [x] **Eval feedback patterns** modul — Jaccard clustering (>0.4), decay 10%/týden
- [x] **Multi-evaluator** modul — N concurrent LLM calls, median, variance >1.5 = warning, feedback z nejhoršího runu
- [x] **Reuse engine** — PatternMatcher (eval-weighted), PipelineComposer (LLM decompose + contract validation), contracts.py
- [x] **Metrics** modul — runs/success/failures/pipeline_reuse, rolling history
- [x] **Brain facade** rozšíření — evaluate(), compose(), get_feedback(), run_aging(), metrics property; recall() s eval_weighted=True
- [x] Unit testy pro každý modul — 107 testů, 92.4% coverage
- [x] Integration test: full learn→eval→feedback→recall→compose cyklus

**Deliverable:** Kompletní Brain knihovna použitelná z Pythonu. Všech 5 core API funguje.

---

### Fáze 2: REST API + Storage backends
> Cíl: Brain jako služba. PostgreSQL pro produkci.

- [x] **FastAPI server**:
  - Konfigurace: env vars (`BRAIN_STORAGE`, `BRAIN_DATABASE_URL`, `BRAIN_LLM_PROVIDER`, ...)
  - App factory pattern (`create_app()`), dependency injection Brain instance
  - Sync endpointy (FastAPI threadpool)
  - Endpoints:
    - `POST /learn` — zaznamenej výsledek běhu
    - `POST /recall` — najdi relevantní agenty
    - `POST /compose` — navrhni pipeline
    - `POST /evaluate` — multi-eval scoring
    - `GET /feedback?task_type=...&limit=4` — top feedback patterns
    - `GET /metrics` — factory metrics
    - `GET /health` — health check
    - `DELETE /patterns/{key}` — smaž pattern (N3)
- [x] **Auth** — Bearer token middleware, validní klíče z env var `BRAIN_API_KEYS`; dev mode pokud prázdné
- [x] **Logging** — `logging.getLogger(__name__)` ve všech modulech (A2)
- [x] **PostgreSQL storage backend** (generický KV + pgvector):
  - SQLAlchemy 2.x: `brain_data` (key TEXT PK, data JSONB) + `brain_embeddings` (key TEXT PK, embedding vector(1536))
  - HNSW index pro `search_similar()` přes pgvector
  - Alembic migrace v `agent_brain/db/migrations/`
  - `PostgresStorage` implementuje `StorageBackend` ABC
- [x] **Docker compose** — brain-api + komentovaný pgvector/pgvector:pg16 (opt-in)
- [x] **Dockerfile** — multi-stage build (builder + runtime)
- [ ] **Model routing** modul — odloženo na Phase 2.5 nebo Phase 3 (není zdrojový kód z Factory V2)
- [x] **API testy** — 19 testů, TestClient + FakeEmbeddings + mocked LLM
- [x] **OpenAPI dokumentace** — auto-generated z Pydantic modelů, Swagger UI na `/docs`

**Bugfixes a architectural improvements implementovány v rámci Phase 2:**
- [x] B1-B4: evaluator num_evals, future timestamps, malformed ISO, last_exc None
- [x] V1-V3: input validation na Brain API, max-length limits, path sanitization
- [x] A3-A5: thread safety (JSONStorage Lock), corrupted storage recovery, shared _extract_json util
- [x] N1-N3: circular pipeline detection, embedding dimension mismatch, delete_pattern API
- [x] A1, N4: roadmap notes pro Phase 4 (custom exceptions, export/import)

**Deliverable:** `docker compose up` spustí Brain API. Swagger UI na `/docs`. 126 testů, pokrytí ≥80%.

---

### Fáze 3: SDK pluginy + Prompt Evolution
> Cíl: Zero-friction integrace do existujících frameworků. Self-improving prompty.

- [ ] **LangChain callback**:
  ```python
  from agent_brain.sdk.langchain import BrainCallback
  chain = LLMChain(..., callbacks=[BrainCallback(brain)])
  ```
  - Auto-learn z chain.run() výsledků
  - Auto-recall relevant context před chain start
- [ ] **CrewAI middleware**:
  ```python
  from agent_brain.sdk.crewai import BrainMiddleware
  crew = Crew(agents=[...], middleware=[BrainMiddleware(brain)])
  ```
- [ ] **Generic webhook** — POST na brain endpoint po každém agent run
- [ ] **Anthropic provider** — `AnthropicProvider` (LLM only, `anthropic` SDK)
- [ ] **Local embeddings provider** — sentence-transformers (no API key needed, dobrý pro OSS adoption)
- [ ] **Prompt evolution** modul:
  - Extrakce z agent_factory_v2/agents/prompt_evolver.py + prompt_ab_tester.py
  - Analýza failure patterns → generate improved prompt candidates
  - A/B testing: eval(candidate) >= eval(current) - 0.2
  - `brain.evolve_prompt(role, current_prompt)` API
- [ ] **Failure clustering** modul:
  - Extrakce z agent_factory_v2/memory/failure_clusterer.py
  - Identifikace systémových problémů
  - `brain.analyze_failures()` API
- [ ] **Skill registry**:
  - Extrakce z agent_factory_v2/memory/skill_registry.py + capability_extractor.py
  - `brain.register_skills()`, `brain.find_by_skills()` API

**Deliverable:** `pip install agent-brain[langchain]` funguje. Prompt evolution API.

---

### Fáze 4: Polish + Launch
> Cíl: Production-ready, publikovatelný na PyPI.

- [ ] **CLI tool**:
  ```bash
  agent-brain init          # inicializace brain_data/
  agent-brain serve         # spustí REST API
  agent-brain status        # metriky, success rate, pattern count
  agent-brain learn <file>  # batch learn z JSONL
  agent-brain recall "task" # semantic search z CLI
  agent-brain aging         # ruční spuštění pattern aging
  ```
  - Implementace: Typer (type hints → CLI automaticky, Rich output, Pydantic synergie)
- [ ] **Dokumentace** — MkDocs + Material:
  - Getting Started (5 min)
  - Core Concepts (patterns, aging, multi-eval, reuse)
  - API Reference (auto-generated)
  - Integration Guides (LangChain, CrewAI, custom)
  - Self-hosting Guide
- [ ] **Benchmark suite** — reprodukce Agent Factory V2 výsledků:
  - 8 standardních tasků, porovnání s/bez Brain
  - Metriky: success rate, reuse rate, avg eval score, LLM cost
  - Publikovat jako "proof that Brain works"
- [ ] **PyPI release** — `pip install agent-brain`
- [ ] **Docker image** — `ghcr.io/agent-brain/agent-brain:latest`
- [ ] **Licence** — finální rozhodnutí před releasem:
  - Záměr: nekomerční použití zdarma, komerční vyžaduje platformu nebo on-prem licenci
  - Zvážit: BSL, AGPL + dual-licensing, custom licence
  - Konzultace s právníkem před zveřejněním
- [ ] **GitHub repo** — README, LICENSE, CONTRIBUTING, CI/CD
- [ ] **Launch blog post** — "How self-learning agents achieve 93% success rate"
- [ ] **Security audit** — dependency scan, API key handling, input validation

**Deliverable:** Veřejný PyPI balíček, Docker image, dokumentace, benchmark výsledky.

---

## Budoucí fáze (po launch)

### Fáze 5: Dashboard + Team features
- Web UI pro vizualizaci patterns, evals, metrics
- Team brain sharing (multi-tenant)
- RBAC (admin, developer, viewer)
- Webhook notifications (Slack, Discord)
- Zvážit: PostgresStorage optimalizace (relační schema místo generického KV)
- Research topic: grafová DB (Neo4j/ArangoDB) pro vizualizaci agent → skill → task vztahů

### Fáze 6: Marketplace
- Sdílení success patterns mezi uživateli
- "Community patterns" — best practices pro běžné task typy
- Monetizace: premium patterns, verified integrations

### Fáze 7: Další embedding providery
- Voyage AI embedding provider (`pip install agent-brain[voyage]`)
- Cohere embeddings
- Dedikovaná vektorová DB (Qdrant/Milvus) jako StorageBackend — pokud scale překročí 100k+ patternů
- Další providery dle poptávky

### Fáze 8: Advanced Learning
- Reinforcement learning z eval scores (ne jen pattern matching)
- Auto-tuning eval promptů (meta-learning)
- Cross-project knowledge transfer

### Pre-launch security checklist
- [ ] API key rotation mechanismus
- [ ] Rate limiting na API endpointech
- [ ] HTTPS enforcement dokumentace (reverse proxy)
- [ ] Rozhodnout: propagovat logging výstupy uživatelům? (aktuálně jen interní)
- [ ] Config file (YAML/TOML) jako optional override pro komplexní konfigurace (model routing per-role)
- [ ] **Custom exception hierarchy** (`BrainError`, `StorageError`, `ProviderError`, `ValidationError`) — nahradit mix `RuntimeError`/`ValueError` v public API; rozhodnout zda exponovat jako public (A1)
- [ ] **brain.export() / brain.import()** — backup/migrate JSON→Postgres; zvážit formát (JSONL, ZIP) (N4)

---

## Metriky úspěchu

| Fáze | KPI | Target | Výsledek |
|------|-----|--------|---------|
| 0-1 | End-to-end test PASS | 100% | ✅ 107 testů, 100% PASS |
| 0-1 | Unit test coverage | ≥80% | ✅ 92.4% |
| 2 | Total tests after Phase 2 | 100% PASS | ✅ 126 testů, 100% PASS |
| 2 | API response time (recall) | <200ms (JSON), <500ms (Postgres) | — (benchmark Phase 4) |
| 2 | API response time (evaluate) | <10s (závisí na LLM) | — (závisí na LLM latency) |
| 3 | Framework plugin adoption | ≥1 framework s fungujícím pluginem | — |
| 4 | PyPI weekly downloads | tracking starts | — |
| 4 | GitHub stars | tracking starts | — |
| 4 | Benchmark: success rate improvement | ≥15% vs baseline bez Brain | — |

---

## Technický stack

| Komponenta | Technologie |
|------------|-------------|
| Jazyk | Python 3.12+ |
| API | FastAPI + uvicorn |
| Data validation | Pydantic v2 |
| DB (optional) | PostgreSQL 16 + pgvector |
| ORM | SQLAlchemy 2.x |
| Migrace | Alembic |
| Embeddings | OpenAI text-embedding-3-small (default) / sentence-transformers (local, no API key) |
| LLM | OpenAI GPT-4.1 / Anthropic Claude / any provider |
| Testy | pytest, pytest-cov, pytest-asyncio |
| CI | GitHub Actions |
| Docs | MkDocs + Material |
| Package | pyproject.toml + hatchling |
| Container | Docker + docker compose |

---

## Struktura projektu

Legenda: ✅ implementováno | 🔲 plánováno

```
agent-brain/
├── CLAUDE.md                    ✅
├── roadmap.md                   ✅
├── README.md                    ✅
├── pyproject.toml               ✅
├── LICENSE                      🔲 Phase 4 (rozhodnutí o licenci před releasem)
├── docker-compose.yml           🔲 Phase 2
├── Dockerfile                   🔲 Phase 2
│
├── agent_brain/
│   ├── __init__.py              ✅ Brain class (public facade)
│   ├── brain.py                 ✅ Brain implementation
│   ├── types.py                 ✅ Pydantic modely (Pattern, Match, EvalResult, Pipeline, ...)
│   │
│   ├── core/                    ✅
│   │   ├── __init__.py
│   │   ├── success_patterns.py  ✅ Pattern storage + aging + reuse tracking
│   │   ├── eval_store.py        ✅ Eval výsledky + eval-weighted multiplier
│   │   ├── eval_feedback.py     ✅ Recurring feedback clustering
│   │   ├── metrics.py           ✅ Run/success/failure/reuse metriky
│   │   ├── agent_registry.py    🔲 Phase 3
│   │   └── skill_registry.py    🔲 Phase 3
│   │
│   ├── reuse/                   ✅
│   │   ├── __init__.py
│   │   ├── matcher.py           ✅ Semantic search + eval weighting
│   │   ├── composer.py          ✅ LLM pipeline decompose + contract validation
│   │   └── contracts.py         ✅ reads/writes chain validation
│   │
│   ├── eval/                    ✅
│   │   ├── __init__.py
│   │   ├── evaluator.py         ✅ MultiEvaluator (N concurrent runs, median, variance)
│   │   ├── variance.py          🔲 Phase 2 (aktuálně součást evaluator.py)
│   │   └── routing.py           🔲 Phase 2
│   │
│   ├── evolution/               🔲 Phase 3 (prázdný stub)
│   │   ├── __init__.py
│   │   ├── prompt_evolver.py    🔲
│   │   ├── ab_tester.py         🔲
│   │   └── failure_cluster.py   🔲
│   │
│   ├── providers/               ✅ částečně
│   │   ├── __init__.py          ✅
│   │   ├── base.py              ✅ ABC: LLMProvider, EmbeddingProvider, StorageBackend
│   │   ├── openai.py            ✅ OpenAI LLM + embeddings (retry, native batch)
│   │   ├── json_storage.py      ✅ JSON atomic storage + cosine similarity
│   │   ├── anthropic.py         🔲 Phase 3
│   │   ├── local.py             🔲 Phase 3 (sentence-transformers)
│   │   └── postgres.py          🔲 Phase 2
│   │
│   ├── api/                     🔲 Phase 2 (prázdný stub)
│   │   ├── __init__.py
│   │   ├── app.py               🔲
│   │   ├── routes.py            🔲
│   │   ├── auth.py              🔲
│   │   └── deps.py              🔲
│   │
│   ├── sdk/                     🔲 Phase 3 (prázdný stub)
│   │   ├── __init__.py
│   │   ├── langchain.py         🔲
│   │   └── crewai.py            🔲
│   │
│   ├── cli/                     🔲 Phase 4 (prázdný stub)
│   │   ├── __init__.py
│   │   └── main.py              🔲
│   │
│   └── db/                      🔲 Phase 2 (prázdný stub)
│       ├── __init__.py
│       ├── models.py            🔲
│       └── migrations/          🔲
│
├── tests/                       ✅ 107 testů, 92.4% coverage
│   ├── conftest.py              ✅ FakeEmbeddings + fixtures
│   ├── test_e2e.py              ✅ learn/recall end-to-end + deduplication
│   ├── test_integration.py      ✅ full cycle (learn→eval→feedback→recall→compose)
│   ├── test_core/               ✅ success_patterns, eval_store, eval_feedback, metrics
│   ├── test_reuse/              ✅ contracts
│   ├── test_eval/               ✅ evaluator
│   ├── test_providers/          ✅ json_storage, openai (mocked)
│   ├── test_evolution/          🔲 Phase 3
│   ├── test_api/                🔲 Phase 2
│   └── test_sdk/                🔲 Phase 3
│
├── docs/                        🔲 Phase 4
│   ├── getting-started.md
│   ├── concepts.md
│   ├── api-reference.md
│   └── integrations.md
│
└── examples/                    🔲 Phase 4
    ├── basic_usage.py
    ├── langchain_integration.py
    └── benchmark.py
```
