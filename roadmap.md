# Engramia — Roadmap

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

| Oblast | My (Engramia) | LangChain/LangSmith | CrewAI | AutoGPT |
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
  - Konfigurace: env vars (`ENGRAMIA_STORAGE`, `ENGRAMIA_DATABASE_URL`, `ENGRAMIA_LLM_PROVIDER`, ...)
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
- [x] **Auth** — Bearer token middleware, validní klíče z env var `ENGRAMIA_API_KEYS`; dev mode pokud prázdné
- [x] **Logging** — `logging.getLogger(__name__)` ve všech modulech (A2)
- [x] **PostgreSQL storage backend** (generický KV + pgvector):
  - SQLAlchemy 2.x: `brain_data` (key TEXT PK, data JSONB) + `brain_embeddings` (key TEXT PK, embedding vector(1536))
  - HNSW index pro `search_similar()` přes pgvector
  - Alembic migrace v `engramia/db/migrations/`
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

- [x] **LangChain callback** (`engramia/sdk/langchain.py`):
  ```python
  from engramia.sdk.langchain import EngramiaCallback
  chain = LLMChain(..., callbacks=[EngramiaCallback(brain)])
  ```
  - Auto-learn z chain.run() výsledků
  - Auto-recall relevant context před chain start
  - Configurable: `auto_learn`, `auto_recall`, `min_score`, `recall_limit`
- [x] **Webhook SDK client** (`engramia/sdk/webhook.py`):
  - Lightweight Python HTTP client (urllib, žádné extra deps)
  - Wrappuje všechny REST API endpointy: learn, recall, evaluate, compose, feedback, metrics, aging, ...
  - Bearer token auth, timeout, error handling
- [x] **Anthropic provider** (`engramia/providers/anthropic.py`):
  - `AnthropicProvider(LLMProvider)` — retry 3x, exponential backoff
  - Lazy import, system prompt via kwargs, text block extraction
- [x] **Local embeddings provider** (`engramia/providers/local_embeddings.py`):
  - `LocalEmbeddings(EmbeddingProvider)` — sentence-transformers
  - Default model: `all-MiniLM-L6-v2` (384-dim)
  - Native batch encoding
- [x] **Prompt evolution** modul (`engramia/evolution/prompt_evolver.py`):
  - `PromptEvolver` — LLM generuje vylepšené prompty z recurring feedback
  - `evolve()` — vrátí kandidáta bez A/B testu
  - `evolve_with_eval()` — plný A/B test (candidate_score >= current_score - 0.2)
  - `brain.evolve_prompt(role, current_prompt)` API na Brain facade
- [x] **Failure clustering** modul (`engramia/evolution/failure_cluster.py`):
  - `FailureClusterer` — Jaccard-based clustering feedback patterns
  - `brain.analyze_failures(min_count)` API na Brain facade
- [x] **Skill registry** (`engramia/core/skill_registry.py`):
  - Explicitní capability tagging patternů
  - `brain.register_skills(key, skills)`, `brain.find_by_skills(required)` API
  - `match_all` / `match_any` mode
- [ ] **CrewAI middleware** — odloženo na post-launch (nestabilní API)

**Backlog fixes implementované v rámci Phase 3:**
- [x] B1: Duplicate import v routes.py
- [x] B2: `Brain.storage_type` property (health endpoint nepoužívá `_storage`)
- [x] B3: Error message `_require_llm()` — generická zpráva
- [x] B4-B5: Shared `jaccard()`, `reuse_tier()`, `PATTERNS_PREFIX` v `_util.py`
- [x] B6: `.bak`/`.tmp` cleanup v `JSONStorage.delete()`
- [x] V1: `POST /aging` + `POST /feedback/decay` API endpointy
- [x] V2: Cleanup providers `__init__.py` docstring
- [x] T1-T3: Unit testy pro matcher, composer, brain, auth (30 nových testů)
- [x] Auth refactor: `require_auth` čte env vars per-request (ne at import time)

**Deliverable:** `pip install engramia[langchain]` funguje. Prompt evolution API. 199 testů, 100% PASS.

---

### Fáze 4: Polish + Launch (code items)
> Cíl: Production-ready codebase, čistá exception handling, export/import, CLI.

- [x] **CLI tool** (Typer + Rich):
  ```bash
  engramia init          # inicializace brain_data/
  engramia serve         # spustí REST API
  engramia status        # metriky, success rate, pattern count
  engramia recall "task" # semantic search z CLI
  engramia aging         # ruční spuštění pattern aging
  ```
- [x] **Custom exception hierarchy** — `EngramiaError`, `ProviderError`, `ValidationError`, `StorageError`; REST API mapuje ProviderError → HTTP 501
- [x] **Export/Import** — `brain.export()` / `brain.import_data()` v JSONL-compatible formátu
- [x] **PyPI metadata** — classifiers, `[project.urls]`, `__version__ = "0.5.0"`
- [x] **Phase 3 REST endpointy** — `POST /evolve`, `/analyze-failures`, `/skills/register`, `/skills/search`
- [x] **Audit bugy opraveny** — B1 (mark_reused), B3 (threshold), B4 (feedback length), B5 (_parse_iso), I1 (HTTP 501)

**Backlog items deferred na Fázi 4.5 (security + hardening):**
- [x] Security audit + hardening (viz Fáze 4.5 níže)

**Deliverable (code):** 270 testů, 81% coverage, CLI fungující, exceptions čisté, export/import hotový, security hardened.

---

### Fáze 4.6: Pre-launch
> Cíl: Vše potřebné pro veřejný release na PyPI, Docker Hub / GHCR a GitHub.

#### Fáze 4.6.0: Branding + Launch infrastruktura
> Blocking fáze — bez těchto kroků nelze nic veřejně publikovat.

**Název a identita:**
- [x] **Finální název produktu** — `engramia` (PyPI + .dev doména volné, EUIPO třída 42 volná)
- [x] **Doménová registrace** — `engramia.dev`
- [x] **Přejmenovat codebase** — rename workflow dokončen (agent_brain → remanence → engramia)

**Účty a repozitář:**
- [x] **GitHub organizace** — `engramia` org; repo `https://github.com/engramia/engramia`
- [x] **PyPI účet** — registrace na pypi.org + Trusted Publisher nastavení (GitHub Actions OIDC, bez API tokenů); environments `pypi` + `testpypi` vytvořeny s `v*` tag protection
- [x] **Docker Hub / GHCR** — namespace `ghcr.io/engramia/engramia`; workflow buildí + pushuje image on release; deploy job SSH-deployuje na VM

**LLM API přístup (nutné pro produkci i beta testování):**
- [x] **OpenAI API klíč** — nakonfigurován na VM (separátní klíč pro staging)
- [ ] **Anthropic API klíč** — volitelný, pro Anthropic provider; stejná cost úroveň

**Hosting REST API (Hetzner VPS):**
- [x] **Hetzner VPS** — CX23 (2 vCPU Intel, 4 GB RAM, ~€3.98/měsíc), region DE (EU data residency); Docker 29.x nainstalován
- [x] **Deploy pipeline** — GitHub Actions SSH deploy (appleboy/ssh-action); `docker compose pull && up -d` on release; privátní GHCR image
- [ ] **PostgreSQL + pgvector** — Docker image `pgvector/pgvector:pg16` na stejném VPS; produkce: encrypted volumes, automated backups
- [ ] **TLS/HTTPS** — Let's Encrypt + Caddy/nginx reverse proxy (`api.engramia.dev`)

**Kontaktní a právní základ:**
- [x] **Projektový email** — `support@engramia.dev`
- [ ] **Doplnit placeholdery v docs/legal/** — pricing URL, Change Date v LICENSE.txt

**Deliverable:** Zaregistrovaná doména, GitHub org + repo, PyPI namespace, funkční beta deploy s HTTPS, API klíče v env.

#### Fáze 4.6.1: Changelog + repo infrastruktura
- [x] **CHANGELOG.md** — Keep a Changelog formát, release notes pro v0.1.0–v0.5.0
- [x] **.dockerignore** — vyloučení testů, docs, .git z Docker kontextu
- [x] **py.typed** — PEP 561 marker pro type checking support

#### Fáze 4.6.2: Licence + právní základ
- [x] **Rozhodnout licenci** — BSL 1.1 → Apache 2.0 (change date 4 roky)
- [x] **LICENSE.txt** — BSL 1.1 plný text s parametry (Licensor, Change Date, Additional Use Grant)
- [x] **Terms of Service** — draft v `docs/legal/TERMS_OF_SERVICE.md` (B2B/B2C, AI Act klauzule, arbitráž Praha)
- [x] **Privacy Policy** — draft v `docs/legal/PRIVACY_POLICY.md` (GDPR, data processing, cookies)
- [x] **Key design decisions** — `docs/legal/key-design-decisions.md` (licenční Q&A, trademark, ToS, AI Act)
- [x] **EU AI Act analýza** — Engramia = minimal/limited risk, compliance klauzule v ToS
- [x] **Žádní externí přispěvatelé** — CONTRIBUTING.md nepotřeba, README note
- [x] **Aktualizovat pyproject.toml** — `license` field (BSL 1.1), classifier `License :: Other/Proprietary License`
- [x] **Cookie Policy** — draft v `docs/legal/COOKIE_POLICY.md` (strictly necessary + opt-in analytics)
- [x] **DPA template** — draft v `docs/legal/DPA_TEMPLATE.md` (GDPR Art. 28, sub-processors, breach notification)

**Deliverable:** LICENSE.txt, ToS, Privacy Policy, Cookie Policy, DPA template, EU AI Act analýza, key design decisions. Vše draft — právní review v Fázi 4.6.2.1.

#### Fáze 4.6.2.1: Právní review + finalizace (post-launch nebo před Cloud tier)
> Cíl: Profesionální právní review všech dokumentů před komerčním nasazením.

- [] **Revize LICENSE.md**:
1) Bod 2 — LICENSE.md strukturální změny (co kam přesunout)
Oficiální BSL 1.1 template má tento závazný pořadí v Parameters (Covenant #4 říká "Not to modify this License in any way"):
2) Přesunout Additional Use Grant z pozice za Change License na pozici před Change Date — správné pořadí je: Licensor → Licensed Work → Additional Use Grant → Change Date → Change License
Přidat copyright inline k Licensed Work — správně: Licensed Work: Engramia, version 0.5.0 (c) 2026 Marek Čermák (aktuální samostatný řádek Copyright (c)... nad Parameters je nestandardní)
3) Celou sekci ## Terms (od "Definitions." po "This License shall be interpreted in good faith.") — smazat a nahradit oficiálním BSL 1.1 boilerplate textem z mariadb.com/bsl11 (aktuální custom text je zásadní porušení Covenant #4 — BSL 1.1 zakazuje modifikaci svého textu)
4) Sekci ## Disclaimer — smazat celou, warranty disclaimer je součástí oficiálního boilerplate ("TO THE EXTENT PERMITTED BY APPLICABLE LAW, THE LICENSED WORK IS PROVIDED ON AN 'AS IS' BASIS...")
5) Sekci ## Notice — rozšířit o celou sadu "Covenants of Licensor" která je součástí oficiálního textu


- [ ] **Právní review ToS** — český advokát: B2C spotřebitelské klauzule, GDPR compliance, arbitrážní doložka
- [ ] **Právní review Privacy Policy** — GDPR compliance, retence, international transfers
- [ ] **Právní review Cookie Policy** — ePrivacy compliance, consent mechanism
- [ ] **Právní review DPA template** — GDPR Art. 28 compliance, sub-processor flow
- [ ] **Právní review LICENSE.txt** — ověření BSL 1.1 parametrů, enforceability
- [ ] **Trademark** — registrace EUIPO (třída 42) po finalizaci názvu produktu
- [ ] **EU AI Act** — monitoring regulatorních updates, delegated acts
- [ ] **Ověřit živnost** — aktivní IČO pro fakturaci
- [x] **Finální název produktu** — `engramia`, doména `engramia.dev` registrována
- [ ] **Doplnit placeholdery** — pricing URL v ToS, Privacy Policy, Cookie Policy, DPA (kontaktní email `support@engramia.dev` již doplněn)
- [ ] **Privacy Policy — šifrování at rest** — doplnit do sekce 7 (Data Security) zmínku o šifrování databáze at rest (PostgreSQL encrypted volumes); aktuálně chybí, přestože TLS in-transit je popsán
- [ ] **Privacy Policy — anonymizace dat** — doplnit do sekce 4.3 popis metody anonymizace (co konkrétně se stripuje, jak se zabrání re-identifikaci); „cannot be re-identified" je právní tvrzení bez technického základu
- [ ] **DPA — doplnit seznam sub-procesorů** — vyplnit konkrétní hosting provider a payment processor v tabulce sub-procesorů (Sec. 4.4); DPA nelze podepsat s TBD položkami
- [ ] **Sub-processor registry stránka** (`/legal/subprocessors`) — veřejná stránka nebo statická stránka v dokumentaci se seznamem aktuálních sub-procesorů, jejich účelem, lokací a datem přidání; vyžadováno DPA Sec. 4.4 (GDPR Art. 28); URL `https://engramia.dev/legal/subprocessors` je již zakotvena v DPA šabloně

#### Fáze 4.6.3: Kvalita kódu + linting
- [x] **Linting config** — ruff + mypy konfigurace v `pyproject.toml`
- [x] **Přidat linting nástroje** do `[dev]` extras (ruff, mypy)
- [x] **Opravit linting/type chyby** — first pass ruff + mypy
- [x] **Volitelně: .pre-commit-config.yaml** — pre-commit hooks pro lokální vývoj

#### Fáze 4.6.4: CI/CD pipeline
- [x] **.github/workflows/ci.yml** — pytest + ruff + mypy na push/PR, Python 3.12 matrix
- [x] **.github/workflows/publish.yml** — build + verify + TestPyPI + PyPI on GitHub release (Trusted Publisher OIDC); pro privátní fázi zakázán (manual `workflow_dispatch` only)
- [x] **.github/workflows/docker.yml** — Docker image build + push na GHCR on release (semver tags) + SSH deploy job na VM

#### Fáze 4.6.5: Dokumentace
- [x] **mkdocs.yml** — MkDocs + Material konfigurace
- [x] **docs/** — Getting Started, Architecture, API Reference, Providers, SDK Integrations, Security
- [x] **.readthedocs.yml** — ReadTheDocs integrace
- [x] **Aktualizovat pyproject.toml URLs** — docs URL na ReadTheDocs

#### Fáze 4.6.6: Examples + launch
- [x] **examples/** — 4–5 runnable příkladů (basic, REST API, LangChain, PostgreSQL, local embeddings)
- [ ] **Benchmark suite** — reprodukce Agent Factory V2 výsledků (93% success rate)
- [ ] **Finální README review** — ověřit vše aktuální
- [ ] **Přepnout repo na public**
- [ ] **PyPI environment protection** — po přepnutí na public: Settings → Environments → `pypi` → Required reviewers (přidat sebe); re-enable release trigger v publish.yml
- [ ] **PyPI release** — `pip install engramia`
- [ ] **Docker image** — `ghcr.io/engramia/engramia:latest` (privátní GHCR staging image běží; veřejný image po přepnutí repo na public)
- [ ] **TLS/HTTPS** — Caddy reverse proxy + Let's Encrypt pro `api.engramia.dev`
- [ ] **Launch blog post** — "How self-learning agents achieve 93% success rate"

**Deliverable (launch):** Veřejný PyPI balíček, Docker image, dokumentace, benchmark výsledky, examples.

#### Fáze 4.6.7: Quick fixes
- [x] **API version DRY** — `app.py` importuje `__version__` místo hardcoded `"0.5.0"`
- [x] **Missing `__init__.py`** — v `engramia/db/migrations/` a `engramia/db/migrations/versions/`
- [x] **Rich explicitní závislost** — přidat `rich>=13.0` do `[cli]` extra v pyproject.toml
- [x] **Placeholder URLs** — `[project.urls]` aktualizovány na `https://github.com/engramia/engramia`

#### Fáze 4.6.8: CrewAI integrace
- [x] **CrewAI middleware** (`engramia/sdk/crewai.py`) — EngramiaCrewCallback pro CrewAI agents
- [x] **Auto-learn** z crew task výsledků, **auto-recall** relevant patterns před task start (inject_recall + kickoff wrapper)
- [x] **Testy** — unit testy (`tests/test_sdk/test_crewai.py`, 19 testů) + příklad v `examples/`
- [x] **Dokumentace** — quick start guide pro CrewAI integraci (`docs/integrations/crewai.md`)

**Deliverable:** `pip install engramia[crewai]` s fungující integrací.

#### Fáze 4.6.9: MCP Server
> Cíl: Table stakes pro 2026. MCP je standard pro interoperabilitu agentů.

- [x] **MCP server** (`engramia/mcp/server.py`) — expose Brain API jako MCP tools
- [x] **MCP tools**: learn, recall, evaluate, compose, feedback, metrics, aging
- [x] **Kompatibilita**: Claude Desktop, Cursor, Windsurf, VS Code Copilot
- [x] **Dokumentace**: MCP setup guide + příklad konfigurace

**Deliverable:** `engramia` jako MCP server použitelný z Claude Desktop a dalších MCP klientů.

---

#### Fáze 4.6.10: Agent Factory V2 integrace (produkční test)
> Cíl: Ověřit Engramia Brain v reálném prostředí — Agent Factory V2 jako první
> skutečný konzument paměťové vrstvy.
>
> Detailní postup: **[docs/integration-agent-factory.md](docs/integration-agent-factory.md)**

**Fáze 1 — Lokální test (docker compose + localhost):**
- [ ] Vytvořit `memory/engramia_bridge.py` v agent_factory_v2 (webhook SDK wrapper, no-op pokud ENGRAMIA_URL není nastaveno)
- [ ] Learn hook v `orchestrator/generation.py` — po úspěšném runu (`add_success_pattern` + eval_score) → `POST /v1/learn`
- [ ] Recall hook v `orchestrator/generation.py` — před code generation → `POST /v1/recall` (log only, no inject v MVP)
- [ ] Ověřit: `python factory.py "task"` → `GET /v1/metrics` → `pattern_count >= 1`
- [ ] Ověřit: druhý recall na podobný task vrátí pattern z prvního runu

**Fáze 2 — Produkční test (Hetzner VM):**
- [ ] Zpřístupnit API: Hetzner firewall + port 8000 OR **Caddy + TLS** → `api.engramia.dev` *(viz Fáze 4.6.6)*
- [ ] Nastavit `ENGRAMIA_API_KEYS` na VM (ověřit že není prázdné/placeholder)
- [ ] Ověřit běžící container: `docker ps | grep engramia`
- [ ] Přepnout agent_factory na VM URL, spustit 3–5 runů s různými tasky
- [ ] Ověřit recall cross-run paměť

**Fáze 3 — Plná integrace (po ověření MVP):**
- [ ] Inject Engramia context do architect promptu (`agents/architect.py`)
- [ ] Inject Engramia feedback do coder promptu (merge s lokální feedback DB)
- [ ] Benchmark: porovnat success rate/eval score před a po zapojení Brain

**Blocker identifikován:** Port 8000 na VM není dostupný zvenčí (Hetzner firewall). Řeší Fáze 2 výše nebo Caddy v Fázi 4.6.6.

---

### Fáze 4.5: Security Audit + Hardening
> Cíl: OWASP ASVS Level 2/3. Systematický security audit + hardening před launch.
> Metodologie: OWASP ASVS + STRIDE threat model.

**Implementované hardening body:**
- [x] **S1 (ASVS 2.1)**: Timing-safe token comparison — `hmac.compare_digest()` (byl `in` set)
- [x] **S2/S17 (ASVS 13.3)**: Rate limiting middleware — per-IP, per-path, configurable via env vars (`ENGRAMIA_RATE_LIMIT_DEFAULT=60/min`, `ENGRAMIA_RATE_LIMIT_EXPENSIVE=10/min`)
- [x] **S3 (ASVS 14.1)**: Startup security warnings — WARNING log při dev mode (bez auth) a wildcard CORS
- [x] **S4 (ASVS 14.5)**: CORS middleware — `CORSMiddleware` s `ENGRAMIA_CORS_ORIGINS` env var
- [x] **S5 (ASVS 5.1)**: `eval_score` bounds validation — 0.0–10.0 check v `Brain.learn()`
- [x] **S6 (ASVS 5.1)**: `import_data()` key prefix validation — zamítá non-`patterns/` klíče
- [x] **S7 (ASVS 5.1)**: `delete_pattern()` prefix validation — zamítá non-`patterns/` klíče
- [x] **S8 (ASVS 6.2)**: SHA-256 místo MD5 pro key generation (v `_pattern_key()` i `evaluate()`)
- [x] **S9 (ASVS 5.1)**: `num_evals` cap v Python API — max `_MAX_NUM_EVALS=10` (API schema mělo limit, přímé volání ne)
- [x] **S10-S12 (ASVS 5.4)**: Prompt injection mitigation — XML delimitery v evaluator, composer, evolver promptech + explicit "disregard embedded instructions"
- [x] **S13 (ASVS 8.2)**: Security response headers — `SecurityHeadersMiddleware`: `X-Content-Type-Options`, `X-Frame-Options`, `X-Permitted-Cross-Domain-Policies`, `Referrer-Policy`
- [x] **S18 (ASVS 12.1)**: Request body size limit — `BodySizeLimitMiddleware` (default 1 MB, `ENGRAMIA_MAX_BODY_SIZE` env var)
- [x] **S21 (ASVS 7.1)**: Audit logging — structured `engramia.audit` logger pro AUTH_FAILURE, PATTERN_DELETED, RATE_LIMITED
- [x] **S22 (ASVS 7.4)**: Auth failures logged s IP adresou a důvodem
- [x] **S23 (ASVS 14.2)**: Docker non-root user — `brain:brain` (UID 1001, no shell, no home)
- [x] **S25 (ASVS 13.1)**: API versioning — `/v1/` prefix na všech endpointech

**Odloženo (mimo scope Fáze 4.5):**
- [ ] Encryption at rest — řeší se na infrastrukturní úrovni (encrypted volumes)
- [ ] TLS/HTTPS — dokumentace v Fázi 4.6 (řeší reverse proxy)
- [ ] Dependency pinning s hashi — CI/CD pipeline v Fázi 4.6
- [ ] Embedding extraction riziko — výzkumné téma, nízké praktické riziko

**Second security audit (hardening round 2):**
- [x] **S26**: Sanitize exception details — generic error messages in HTTP responses, internal details logged server-side only
- [x] **S27**: CORS disabled by default — `ENGRAMIA_CORS_ORIGINS` defaults to empty (not `*`)
- [x] **S28**: Path traversal prevention — `..` sequences rejected in pattern keys (delete + import)
- [x] **S29**: LIKE wildcard escaping — `%` and `_` escaped in PostgreSQL `LIKE` queries
- [x] **S30**: API schema `max_length` — all string fields have explicit length limits in Pydantic models
- [x] **S31**: API key count removed from startup log (information leak)
- [x] **S32**: Content-Type validation in webhook SDK client
- [x] **S33**: Structured JSON audit logging — `json.dumps()` instead of dict repr
- [x] **SECURITY.md** — documented 10 known limitations + production deployment checklist

**Deliverable:** 270 testů (vč. 30 security testů), 81% coverage, OWASP ASVS Level 2 compliance, SECURITY.md.

---

## Budoucí fáze (po launch)

### Fáze 5: Platform + Enterprise
> Cíl: Team features, observability, compliance. Enterprise-ready.

- [ ] Web UI / Dashboard — vizualizace patterns, evals, metrics
- [ ] Team brain sharing (multi-tenant)
- [ ] RBAC (admin, developer, viewer)
- [ ] SSO/SAML integrace
- [ ] OpenTelemetry integrace — traces/spans pro Langfuse, Datadog, Grafana
- [ ] GDPR compliance — right to erasure s provenance, data residency controls (EU/US/APAC), DPA enforcement
- [ ] B2C ToS consent flow — aktivní opt-in pro materiální změny ToS (Sec. 15.5.2):
  - Při materiální změně ToS systém vygeneruje consent request — uživatel dostane email s odkazem na diff změn a tlačítkem "I accept the updated Terms"
  - Consent se uloží do DB s timestampem, verzí ToS a user ID (auditovatelný trail)
  - Uživatelé, kteří nepotvrdí do 30 dní, mají přístup dál za podmínek předchozí verze, ale nemohou upgradovat tier ani prodloužit subscription
  - Fallback: při neudělení souhlasu do 60 dní = výzva k ukončení, nebo automatické downgrade na Free tier
- [ ] Webhook notifications (Slack, Discord)
- [ ] API key rotation mechanismus
- [ ] Config file (YAML/TOML) jako optional override
- [ ] SOC 2 security controls — implementace kontrol bez certifikace (viz Security Requirements níže)
- [ ] Zvážit: PostgresStorage optimalizace (relační schema místo generického KV)

### Fáze 6: Memory Architecture
> Cíl: Cutting-edge memory systém. Knowledge graph, memory taxonomie, komprese.

- [ ] **Knowledge Graph** — entity/relationship vrstva nad patterny (task → skill → pattern vztahy)
- [ ] **Memory taxonomie** — explicitní separace episodic (konkrétní běhy), semantic (fakta, entity), procedural (naučené dovednosti/pravidla)
- [ ] **Memory compression / summarization** — shrnutí starých patternů místo pouhého decay na skóre
- [ ] **Multi-agent memory sharing** — sdílené pattern pools s access control a conflict resolution
- [ ] Research topic: grafová DB (Neo4j/ArangoDB) pro vizualizaci agent → skill → task vztahů

### Fáze 7: Multimodal + Providers
> Cíl: Rozšíření za text-only. Další embedding a storage providery.

- [ ] **Multimodal memory** — ukládání referencí na obrázky/audio/video s textovými popisy
- [ ] Voyage AI embedding provider (`pip install engramia[voyage]`)
- [ ] Cohere embeddings
- [ ] Dedikovaná vektorová DB (Qdrant/Milvus) jako StorageBackend — pokud scale překročí 100k+ patternů

### Fáze 8: Marketplace
> Cíl: Community-driven pattern sharing a monetizace.

- [ ] Sdílení success patterns mezi uživateli
- [ ] "Community patterns" — best practices pro běžné task typy
- [ ] Monetizace: premium patterns, verified integrations

### Fáze 9: Advanced Learning
> Cíl: RL, meta-learning, cross-project transfer.

- [ ] Reinforcement learning z eval scores (ne jen pattern matching)
- [ ] Auto-tuning eval promptů (meta-learning)
- [ ] Cross-project knowledge transfer

---

### Security Requirements (SOC 2 Trust Criteria — bez certifikace)
> Cíl: Dodržovat bezpečnostní kontroly SOC 2 Type 2 bez formální certifikace.
> Implementace průběžně v Phase 5+.

**Implementováno (Phase 4.5):**
- [x] CC6.1: Logické přístupové kontroly (Bearer token auth, timing-safe comparison)
- [x] CC6.6: Security headers, CORS, rate limiting, body size limit
- [x] CC7.1: Audit logging (structured JSON — AUTH_FAILURE, PATTERN_DELETED, RATE_LIMITED)
- [x] CC8.1: Input validation, path traversal prevention, SQL injection prevention

**Plánováno (Phase 5+):**
- [ ] CC6.2: Multi-factor authentication (SSO/SAML)
- [ ] CC6.3: Role-based access control (RBAC) — per-team, per-project isolation
- [ ] CC7.2: Incident response — dokumentovaný IR playbook, kontaktní body, eskalace
- [ ] CC7.3: Change management — povinný code review, approval flow, audit trail
- [ ] CC7.4: Vulnerability management — dependency scanning (Dependabot/Snyk), CVE monitoring
- [ ] A1.2: Backup and recovery — automatické zálohy, definované RTO/RPO cíle
- [ ] C1.1: Data classification — kategorizace dat (public, internal, confidential, restricted)
- [ ] C1.2: Encryption at rest — customer-managed encryption keys (CMEK), encrypted volumes
- [ ] P1–P4: Privacy — data collection, use, retention, disposal policies (GDPR Art. 5, 6, 17)
- [ ] P6–P8: Privacy — access controls, disclosure safeguards, data quality

### Pre-launch checklist (backlog z dřívějších fází)
- [x] ~~Rate limiting na API endpointech~~ — implementováno v Phase 4.5
- [x] ~~Custom exception hierarchy~~ — implementováno v Phase 4 (`EngramiaError`, `ProviderError`, `ValidationError`, `StorageError`)
- [x] ~~brain.export() / brain.import()~~ — implementováno v Phase 4
- [x] ~~HTTPS enforcement dokumentace~~ — zdokumentováno v SECURITY.md
- [ ] API key rotation mechanismus — post-launch (Phase 5+)
- [ ] Config file (YAML/TOML) jako optional override — post-launch (Phase 5+)

---

## Metriky úspěchu

| Fáze | KPI | Target | Výsledek |
|------|-----|--------|---------|
| 0-1 | End-to-end test PASS | 100% | ✅ 107 testů, 100% PASS |
| 0-1 | Unit test coverage | ≥80% | ✅ 92.4% |
| 2 | Total tests after Phase 2 | 100% PASS | ✅ 126 testů, 100% PASS |
| 2 | API response time (recall) | <200ms (JSON), <500ms (Postgres) | — (benchmark Phase 4) |
| 2 | API response time (evaluate) | <10s (závisí na LLM) | — (závisí na LLM latency) |
| 3 | Total tests after Phase 3 | 100% PASS | ✅ 199 testů, 100% PASS |
| 3 | Framework plugin adoption | ≥1 framework s fungujícím pluginem | ✅ LangChain EngramiaCallback |
| 4 | Total tests after Phase 4 | 100% PASS | ✅ 240 testů, 81% coverage |
| 4 | CLI tool | engramia CLI fungující | ✅ init, serve, status, recall, aging |
| 4.5 | Security tests | OWASP ASVS Level 2/3 | ✅ 270 testů (30 security), 81% coverage |
| 4.5 | STRIDE audit resolved | všechna HIGH/MEDIUM | ✅ 24 bodů implementováno + SECURITY.md |
| 4.6.1 | CHANGELOG + repo infra | CHANGELOG, .dockerignore, py.typed | ✅ |
| 4.6 | PyPI weekly downloads | tracking starts | — |
| 4.6 | GitHub stars | tracking starts | — |
| 4.6 | Benchmark: success rate improvement | ≥15% vs baseline bez Brain | — |
| 4.6.8 | CrewAI integrace | Fungující `pip install engramia[crewai]` | — |
| 4.6.9 | MCP server | Fungující MCP integrace s Claude Desktop | — |
| 5 | Enterprise features | RBAC + SSO + OTEL + GDPR | — |
| 6 | Memory architecture | Knowledge graph + taxonomie + compression | — |
| 7 | Multimodal | ≥1 non-text modality podporována | — |

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
engramia/
├── CLAUDE.md                    ✅
├── roadmap.md                   ✅
├── README.md                    ✅
├── CHANGELOG.md                 ✅ Phase 4.6.1
├── SECURITY.md                  ✅ Phase 4.5
├── pyproject.toml               ✅
├── LICENSE                      🔲 Phase 4.6.2 (rozhodnutí o licenci)
├── CONTRIBUTING.md              🔲 Phase 4.6.2
├── .dockerignore                ✅ Phase 4.6.1
├── .github/workflows/           🔲 Phase 4.6.4
├── docker-compose.yml           ✅
├── Dockerfile                   ✅
│
├── engramia/
│   ├── __init__.py              ✅ Brain class + exceptions + __version__
│   ├── brain.py                 ✅ Brain implementation
│   ├── types.py                 ✅ Pydantic modely (Pattern, Match, EvalResult, Pipeline, ...)
│   ├── _util.py                 ✅ Shared utilities (jaccard, reuse_tier, extract_json_from_llm)
│   ├── exceptions.py            ✅ EngramiaError, ProviderError, ValidationError, StorageError
│   │
│   ├── core/                    ✅
│   │   ├── __init__.py
│   │   ├── success_patterns.py  ✅ Pattern storage + aging + reuse tracking
│   │   ├── eval_store.py        ✅ Eval výsledky + eval-weighted multiplier
│   │   ├── eval_feedback.py     ✅ Recurring feedback clustering
│   │   ├── metrics.py           ✅ Run/success/failure/reuse metriky
│   │   └── skill_registry.py    ✅ Explicit capability tagging + search
│   │
│   ├── reuse/                   ✅
│   │   ├── __init__.py
│   │   ├── matcher.py           ✅ Semantic search + eval weighting
│   │   ├── composer.py          ✅ LLM pipeline decompose + contract validation
│   │   └── contracts.py         ✅ reads/writes chain validation
│   │
│   ├── eval/                    ✅
│   │   ├── __init__.py
│   │   └── evaluator.py         ✅ MultiEvaluator (N concurrent runs, median, variance)
│   │
│   ├── evolution/               ✅
│   │   ├── __init__.py
│   │   ├── prompt_evolver.py    ✅ LLM prompt evolution + A/B testing
│   │   └── failure_cluster.py   ✅ Jaccard-based feedback clustering
│   │
│   ├── providers/               ✅
│   │   ├── __init__.py          ✅ Lazy loading for optional providers
│   │   ├── base.py              ✅ ABC: LLMProvider, EmbeddingProvider, StorageBackend
│   │   ├── openai.py            ✅ OpenAI LLM + embeddings (retry, native batch)
│   │   ├── json_storage.py      ✅ JSON atomic storage + cosine similarity
│   │   ├── anthropic.py         ✅ Anthropic Claude (lazy import, retry, backoff)
│   │   ├── local_embeddings.py  ✅ sentence-transformers (384-dim, native batch)
│   │   └── postgres.py          ✅ PostgreSQL + pgvector (HNSW index)
│   │
│   ├── api/                     ✅
│   │   ├── __init__.py
│   │   ├── app.py               ✅ FastAPI app factory, env var config
│   │   ├── routes.py            ✅ 14 REST endpoints (incl. Phase 3+4)
│   │   ├── auth.py              ✅ Bearer token middleware (per-request)
│   │   ├── deps.py              ✅ Dependency injection (Brain singleton)
│   │   └── schemas.py           ✅ Request/Response Pydantic modely
│   │
│   ├── sdk/                     ✅ (CrewAI deferred to post-launch)
│   │   ├── __init__.py
│   │   ├── langchain.py         ✅ EngramiaCallback (auto-learn, auto-recall)
│   │   └── webhook.py           ✅ Lightweight HTTP client (urllib only)
│   │
│   ├── cli/                     ✅ Phase 4
│   │   ├── __init__.py
│   │   └── main.py              ✅ Typer CLI — init, serve, status, recall, aging
│   │
│   └── db/                      ✅
│       ├── __init__.py
│       ├── models.py            ✅ SQLAlchemy 2.x modely (BrainData, BrainEmbedding)
│       └── migrations/          ✅ Alembic (001_initial: schema + HNSW index)
│
├── tests/                       ✅ 270 testů, 81% coverage
│   ├── conftest.py              ✅ FakeEmbeddings + fixtures
│   ├── test_e2e.py              ✅ learn/recall end-to-end + deduplication
│   ├── test_integration.py      ✅ full cycle (learn→eval→feedback→recall→compose)
│   ├── test_brain.py            ✅ Brain facade
│   ├── test_brain_export.py     ✅ export/import (Phase 4)
│   ├── test_brain_reuse.py      ✅ mark_reused on recall (Phase 4)
│   ├── test_exceptions.py       ✅ exception hierarchy (Phase 4)
│   ├── test_core/               ✅ success_patterns, eval_store, eval_feedback, metrics, skill_registry
│   ├── test_reuse/              ✅ contracts, matcher, composer
│   ├── test_eval/               ✅ evaluator
│   ├── test_providers/          ✅ json_storage, openai, anthropic, local_embeddings
│   ├── test_evolution/          ✅ prompt_evolver, failure_cluster
│   ├── test_api/                ✅ routes, auth, phase3_routes
│   ├── test_sdk/                ✅ langchain, webhook
│   └── test_cli/                ✅ CLI commands (Phase 4)
│
├── docs/                        ✅ Phase 4.6.5
│   ├── index.md
│   ├── getting-started.md
│   ├── concepts.md
│   ├── api-reference.md
│   ├── rest-api.md
│   ├── providers.md
│   ├── cli.md
│   ├── deployment.md
│   ├── security.md
│   └── integrations/
│       ├── langchain.md
│       ├── mcp.md
│       └── webhook.md
│
└── examples/                    🔲 Phase 4.6.6
    ├── basic_usage.py
    ├── langchain_integration.py
    └── benchmark.py
```
