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
  - `brain.recall(task) -> list[Match]` → semantic search
- [x] Jeden end-to-end test: learn → recall → assert match
- [x] README.md s quick-start příkladem

**Deliverable:** `pip install -e .` funguje, learn/recall funguje s OpenAI embeddings + JSON storage.

---

### Fáze 1: Core Brain
> Cíl: Plný learning cyklus — learn, recall, evaluate, compose, improve.

- [ ] **Success patterns** modul:
  - Extrakce z agent_factory_v2/memory/success_patterns.py
  - Pattern aging (time decay 2%/týden)
  - Jaccard similarity matching
  - Reuse tracking (mark_reused, reuse_count boost)
- [ ] **Eval store** modul:
  - Extrakce z agent_factory_v2/memory/eval_store.py
  - Eval-weighted agent scoring
  - Rolling window (max 200 entries)
- [ ] **Eval feedback patterns** modul:
  - Extrakce z agent_factory_v2/memory/eval_feedback_patterns.py
  - Recurring issue tracking
  - Faster decay (10%/týden)
  - `brain.get_feedback(task_type, limit)` API
- [ ] **Multi-evaluator** modul:
  - Extrakce z agent_factory_v2/agents/eval_agent.py
  - N concurrent LLM calls, median aggregace
  - Variance detection (>1.5 = warning)
  - Adversarial check (hardcoded output detection)
  - `brain.evaluate(task, code, output)` API
- [ ] **Reuse engine** modul:
  - Extrakce z agent_factory_v2/agents/composer.py + stage_composer.py
  - Semantic search + eval weighting
  - Three-tier: duplicate (>0.92) / adapt (0.70-0.92) / fresh (<0.70)
  - Contract validation (reads/writes chain)
  - `brain.compose(task)` API
- [ ] **Metrics** modul:
  - Extrakce z agent_factory_v2/memory/factory_metrics.py
  - Run/success/failure tracking
  - `brain.metrics` property
- [ ] **Brain facade** rozšíření:
  - `brain.learn()`, `brain.recall()`, `brain.evaluate()`, `brain.compose()`
  - `brain.get_feedback()`, `brain.metrics`, `brain.run_aging()`
- [ ] Unit testy pro každý modul (target: 80% coverage)
- [ ] Integration test: full learn→eval→feedback→recall→compose cyklus

**Deliverable:** Kompletní Brain knihovna použitelná z Pythonu. Všech 5 core API funguje.

---

### Fáze 2: REST API + Storage backends
> Cíl: Brain jako služba. PostgreSQL pro produkci.

- [ ] **FastAPI server**:
  - `POST /learn` — zaznamenej výsledek běhu
  - `GET /recall?task=...&limit=5` — najdi relevantní agenty
  - `POST /compose` — navrhni pipeline (JSON body: task, constraints, ...)
  - `POST /evaluate` — multi-eval scoring
  - `GET /feedback?task_type=...&limit=4` — top feedback patterns
  - `GET /routing` — model routing doporučení
  - `GET /metrics` — factory metrics
  - `GET /health` — health check
- [ ] **Auth** — API key autentizace (Bearer token)
- [ ] **PostgreSQL storage backend**:
  - SQLAlchemy 2.x modely (runs, evals, patterns, embeddings) v `agent_brain/db/`
  - pgvector pro embedding search (`<=>` cosine distance) — implementuje `search_similar()` přes vector index
  - Alembic migrace v `agent_brain/db/migrations/`
  - `PostgresStorage` implementuje `StorageBackend` ABC
- [ ] **Docker compose** — brain-api + postgres + pgvector
- [ ] **Model routing** modul:
  - Extrakce z agent_factory_v2/agents/routing_analyzer.py
  - Empirická analýza: nejlevnější model s ≥90% kvality
  - `GET /routing` endpoint
- [ ] API testy (httpx + pytest)
- [ ] OpenAPI dokumentace (auto-generated)

**Deliverable:** `docker compose up` spustí Brain API s PostgreSQL. Swagger UI na `/docs`.

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

### Fáze 6: Marketplace
- Sdílení success patterns mezi uživateli
- "Community patterns" — best practices pro běžné task typy
- Monetizace: premium patterns, verified integrations

### Fáze 7: Další embedding providery
- Voyage AI embedding provider (`pip install agent-brain[voyage]`)
- Cohere embeddings
- Další providery dle poptávky

### Fáze 8: Advanced Learning
- Reinforcement learning z eval scores (ne jen pattern matching)
- Auto-tuning eval promptů (meta-learning)
- Cross-project knowledge transfer

---

## Metriky úspěchu

| Fáze | KPI | Target |
|------|-----|--------|
| 0-1 | End-to-end test PASS | 100% |
| 1 | Unit test coverage | ≥80% |
| 2 | API response time (recall) | <200ms (JSON), <500ms (Postgres) |
| 2 | API response time (evaluate) | <10s (závisí na LLM) |
| 3 | Framework plugin adoption | ≥1 framework s fungujícím pluginem |
| 4 | PyPI weekly downloads | tracking starts |
| 4 | GitHub stars | tracking starts |
| 4 | Benchmark: success rate improvement | ≥15% vs baseline bez Brain |

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

## Struktura projektu (target)

```
agent-brain/
├── CLAUDE.md
├── roadmap.md
├── README.md
├── pyproject.toml
├── LICENSE
├── docker-compose.yml
├── Dockerfile
│
├── agent_brain/
│   ├── __init__.py              # Brain class (public facade)
│   ├── types.py                 # Pydantic models (Match, EvalResult, Pattern, ...)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── success_patterns.py  # Pattern storage + aging + matching
│   │   ├── eval_store.py        # Eval results storage
│   │   ├── eval_feedback.py     # Recurring quality issue tracking
│   │   ├── metrics.py           # Run/success/failure tracking
│   │   ├── agent_registry.py    # Agent metadata (reads/writes/capabilities)
│   │   └── skill_registry.py    # Skill → agent mapping
│   │
│   ├── reuse/
│   │   ├── __init__.py
│   │   ├── matcher.py           # Semantic search + eval weighting
│   │   ├── composer.py          # Multi-agent pipeline composition
│   │   └── contracts.py         # reads/writes contract validation
│   │
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── evaluator.py         # Multi-eval scoring engine
│   │   ├── variance.py          # Variance detection + adversarial check
│   │   └── routing.py           # Model routing analyzer
│   │
│   ├── evolution/
│   │   ├── __init__.py
│   │   ├── prompt_evolver.py    # Prompt improvement from failure patterns
│   │   ├── ab_tester.py         # A/B test prompt candidates
│   │   ├── failure_cluster.py   # Failure pattern clustering
│   │   └── aging.py             # Pattern aging orchestration
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py              # ABC: LLMProvider, EmbeddingProvider, StorageBackend (vč. search_similar)
│   │   ├── openai.py            # OpenAI LLM + embeddings
│   │   ├── anthropic.py         # Claude LLM (anthropic SDK)
│   │   ├── local.py             # sentence-transformers embeddings (no API key)
│   │   ├── json_storage.py      # JSON file storage (default)
│   │   └── postgres.py          # PostgreSQL + pgvector storage
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI application
│   │   ├── routes.py            # API endpoints
│   │   ├── auth.py              # API key auth
│   │   └── deps.py              # Dependency injection (Brain instance)
│   │
│   ├── sdk/
│   │   ├── __init__.py
│   │   ├── langchain.py         # LangChain BrainCallback
│   │   └── crewai.py            # CrewAI BrainMiddleware
│   │
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py              # CLI entry point (Typer)
│   │
│   └── db/
│       ├── __init__.py
│       ├── models.py            # SQLAlchemy models
│       └── migrations/          # Alembic
│
├── tests/
│   ├── conftest.py
│   ├── test_core/
│   ├── test_reuse/
│   ├── test_eval/
│   ├── test_evolution/
│   ├── test_providers/
│   ├── test_api/
│   └── test_sdk/
│
├── docs/
│   ├── getting-started.md
│   ├── concepts.md
│   ├── api-reference.md
│   └── integrations.md
│
└── examples/
    ├── basic_usage.py
    ├── langchain_integration.py
    └── benchmark.py
```
