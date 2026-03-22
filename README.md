# Agent Brain

Self-learning memory layer for AI agent frameworks.

[![Tests](https://img.shields.io/badge/tests-268%20passed-brightgreen)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-81%25-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)

> **Status:** Phases 0–4.5 complete — core library + REST API + SDK plugins + prompt evolution + CLI + exceptions + export/import + security hardening (OWASP ASVS Level 2/3).
> See [roadmap.md](roadmap.md) for what's next.

---

## Co to je

Agent Brain řeší problém, který má každý agent framework: **agenti se neučí z předchozích běhů**.

LangChain, CrewAI, AutoGPT a podobné frameworky jsou statické — každý běh začíná od nuly.
Brain je paměťová vrstva, kterou přidáš pod jakýkoli framework a která:

- **Pamatuje** co fungovalo (success patterns s time-decay)
- **Hledá** relevantní agenty pro nový task (semantic search + eval weighting)
- **Skládá** multi-agent pipeline z ověřených komponent (contract validation)
- **Hodnotí** kvalitu kódu (multi-evaluator s variance detection)
- **Zlepšuje** se automaticky (feedback injection, pattern aging)

Extrahováno z Agent Factory V2 — systému, který se za 254 běhů naučil dosahovat 93% success rate.

---

## Instalace

```bash
# Základ (JSON storage, bez LLM/embeddings providera)
pip install agent-brain

# S OpenAI providerem (doporučeno pro začátek)
pip install "agent-brain[openai]"

# REST API + PostgreSQL
pip install "agent-brain[openai,api,postgres]"
```

### Optional extras

| Extra | Obsah | Stav |
|-------|-------|------|
| `openai` | OpenAI LLM + embeddings provider | ✅ |
| `postgres` | PostgreSQL + pgvector storage backend | ✅ |
| `api` | FastAPI REST server | ✅ |
| `anthropic` | Anthropic/Claude LLM provider | ✅ |
| `local` | sentence-transformers embeddings, bez API klíče | ✅ |
| `langchain` | LangChain BrainCallback | ✅ |
| `crewai` | CrewAI BrainMiddleware | Post-launch |
| `cli` | CLI tool (Typer + Rich) | ✅ |
| `dev` | pytest, coverage, vývojové nástroje | ✅ |

---

## Rychlý start

```python
from agent_brain import Brain
from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

brain = Brain(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)
```

---

## Python API Reference

### `brain.learn(task, code, eval_score, output=None) → LearnResult`

Zaznamená výsledek běhu. Uloží success pattern, aktualizuje metriky.

```python
result = brain.learn(
    task="Parse CSV file and compute statistics",
    code="import csv\nimport statistics\n...",
    eval_score=8.5,
    output="mean=42.3, std=7.1",  # optional: stdout agenta
)
print(result.stored)        # True
print(result.pattern_count) # celkový počet patternů
```

- `eval_score` — číslo 0–10, jak dobře agent splnil task
- Pattern se automaticky deduplikuje s existujícími podobnými patterny (Jaccard > 0.7)

---

### `brain.recall(task, limit=5, deduplicate=True, eval_weighted=True) → list[Match]`

Najde relevantní success patterny pro nový task pomocí semantic search.

```python
matches = brain.recall(task="Read CSV and calculate averages", limit=5)

for m in matches:
    print(f"{m.similarity:.2f} | score={m.pattern.success_score:.1f} | {m.pattern.task}")
    print(f"  key: {m.pattern_key}")   # použij pro delete_pattern()
```

Každý `Match` obsahuje:
- `similarity` — kosínová podobnost embedingů (0.0–1.0)
- `reuse_tier` — `"duplicate"` / `"adapt"` / `"fresh"` dle similarity thresholdů
- `pattern_key` — storage klíč pro `delete_pattern()`
- `pattern` — `Pattern` objekt s `task`, `design`, `success_score`, `reuse_count`

Parametry:
- `deduplicate=True` — seskupí patterny stejného tasku (Jaccard > 0.7), vrátí jen top-scoring per skupina
- `eval_weighted=True` — podobnost se násobí multiplikátorem [0.5, 1.0] dle eval skóre; nehodnocené patterny dostávají 0.75

---

### `brain.evaluate(task, code, output=None, num_evals=3) → EvalResult`

Spustí N nezávislých LLM evaluací a agreguje výsledky. Vyžaduje `llm` provider.

```python
result = brain.evaluate(
    task="Parse CSV file",
    code="import csv\n...",
    output="done",    # optional
    num_evals=3,      # počet paralelních LLM evaluací (min 1)
)

print(result.median_score)       # agregované skóre (0–10)
print(result.variance)           # rozptyl skóre mezi runy
print(result.high_variance)      # True pokud variance > 1.5
print(result.feedback)           # doporučení z nejhoršího runu
print(result.adversarial_detected)  # True pokud kód obsahuje hardcoded output
```

- Evaluace běží paralelně (ThreadPoolExecutor)
- Feedback pochází z nejhoršího runu (nejrelevantnější pro zlepšení)
- Detekce adversarial kódu (hardcoded output místo výpočtu)

---

### `brain.compose(task) → Pipeline`

Rozloží task na staged pipeline z existujících success patternů. Vyžaduje `llm` provider.

```python
pipeline = brain.compose(task="Fetch stock data, compute moving average, write report")

print(f"valid={pipeline.valid}, errors={pipeline.contract_errors}")
for stage in pipeline.stages:
    print(f"[{stage.task}]  reads={stage.reads}  writes={stage.writes}")
```

- LLM dekomponuje task na 2–4 stages
- Každá stage je matchována se success patterny přes semantic search
- Contract validation ověří konzistenci data flow (reads/writes chain) včetně detekce cyklů
- Fallback na single-stage pipeline pokud LLM selže

---

### `brain.get_feedback(task_type=None, limit=5) → list[str]`

Vrátí opakující se feedback patterny pro injekci do promptů.

```python
feedback = brain.get_feedback(limit=4)
# ["Add error handling for missing input files.",
#  "Validate CSV headers before processing.", ...]
```

- Vrací pouze feedback s `count >= 2` (opakující se problémy)
- Seřazeno dle četnosti a čerstvosti (skóre × count)
- Vhodné pro automatickou injekci do system promptu codera

---

### `brain.delete_pattern(pattern_key) → bool`

Trvale smaže uložený pattern. Vrátí `True` pokud pattern existoval.

```python
matches = brain.recall(task="Parse CSV")
deleted = brain.delete_pattern(matches[0].pattern_key)
print(deleted)  # True
```

---

### `brain.run_aging() → int`

Aplikuje time-decay na všechny success patterny. Vrátí počet odstraněných patternů.

```python
pruned = brain.run_aging()
print(f"Odstraněno {pruned} zastaralých patternů")
```

- Decay: 2% za týden (`success_score *= 0.98^weeks`)
- Pattern se odstraní pokud `success_score < 0.1`
- Doporučeno spouštět periodicky (např. jednou týdně)

---

### `brain.metrics → Metrics`

Aktuální metriky brain instance.

```python
m = brain.metrics

print(m.runs)            # celkový počet zaznamenaných běhů
print(m.success_rate)    # podíl úspěšných běhů
print(m.avg_eval_score)  # průměrné eval skóre (None pokud žádné eval)
print(m.pattern_count)   # aktuální počet success patternů
print(m.pipeline_reuse)  # počet běhů kde byl použit existující pattern
```

---

### `brain.evolve_prompt(role, current_prompt) → EvolutionResult`

Vygeneruje vylepšený prompt na základě opakujících se kvalitativních problémů.

```python
result = brain.evolve_prompt(role="coder", current_prompt="You are a coder...")
if result.accepted:
    print(result.improved_prompt)
    print(f"Changes: {result.changes}")
```

- Analyzuje top feedback patterny z eval history
- LLM generuje vylepšenou verzi promptu
- Vrátí kandidáta pro ruční/automatické A/B testování

---

### `brain.analyze_failures(min_count=1) → list[FailureCluster]`

Seskupí opakující se chyby do clusterů pro identifikaci systémových problémů.

```python
clusters = brain.analyze_failures(min_count=2)
for c in clusters:
    print(f"{c.representative} (count={c.total_count}, members={len(c.members)})")
```

---

### `brain.register_skills(pattern_key, skills)` / `brain.find_by_skills(required)`

Skill registry pro capability-based vyhledávání patternů.

```python
# Register
matches = brain.recall(task="Parse CSV")
brain.register_skills(matches[0].pattern_key, ["csv_parsing", "statistics"])

# Find
results = brain.find_by_skills(["csv_parsing"], match_all=True)
```

---

### `brain.export() → list[dict]` / `brain.import_data(records, overwrite=False) → int`

Záloha a migrace patternů (JSON storage → PostgreSQL nebo naopak).

```python
# Export všech patternů do JSONL souboru
import json

records = brain.export()
with open("backup.jsonl", "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")

# Import ze zálohy do nové instance
with open("backup.jsonl") as f:
    records = [json.loads(line) for line in f]

new_brain = Brain(embeddings=embeddings, storage=postgres_storage)
imported = new_brain.import_data(records)
print(f"Importováno {imported} patternů")
```

---

### Exceptions

Brain používá vlastní hierarchii výjimek pro přesné error handling:

```python
from agent_brain import BrainError, ProviderError, ValidationError, StorageError

try:
    result = brain.evaluate(task, code)
except ProviderError:
    # LLM provider není nakonfigurován
    pass
except ValidationError:
    # Neplatný vstup (prázdný task, příliš dlouhý kód, ...)
    pass
except BrainError:
    # Jakákoli Brain výjimka
    pass
```

---

### LangChain integrace

```python
from agent_brain.sdk.langchain import BrainCallback

callback = BrainCallback(brain, auto_learn=True, auto_recall=True)
chain = LLMChain(llm=llm, prompt=prompt, callbacks=[callback])
# Brain se automaticky učí z chain runs a recalluje relevantní kontext
```

---

### Webhook SDK klient

```python
from agent_brain.sdk.webhook import BrainWebhook

hook = BrainWebhook(url="http://localhost:8000", api_key="sk-...")
hook.learn(task="Parse CSV", code=code, eval_score=8.5)
matches = hook.recall(task="Read CSV and compute averages")
```

---

## REST API

### Spuštění

```bash
# JSON storage (dev, žádná DB)
docker compose up

# PostgreSQL storage (prod)
BRAIN_STORAGE=postgres \
BRAIN_DATABASE_URL=postgresql://user:pass@localhost:5432/brain \
OPENAI_API_KEY=sk-... \
docker compose up
```

Po startu: Swagger UI na [http://localhost:8000/docs](http://localhost:8000/docs)

### Konfigurace (env vars)

| Proměnná | Default | Popis |
|----------|---------|-------|
| `BRAIN_STORAGE` | `json` | `json` nebo `postgres` |
| `BRAIN_DATA_PATH` | `./brain_data` | Cesta pro JSON storage |
| `BRAIN_DATABASE_URL` | — | PostgreSQL URL (jen pro `postgres`) |
| `BRAIN_LLM_PROVIDER` | `openai` | LLM provider |
| `BRAIN_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API klíč |
| `BRAIN_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `BRAIN_API_KEYS` | *(prázdné)* | Bearer tokeny (prázdné = dev mode, bez auth) |
| `BRAIN_PORT` | `8000` | Port |

### Endpointy

Všechny endpointy jsou dostupné pod prefixem `/v1/`:

| Metoda | Cesta | Popis |
|--------|-------|-------|
| `POST` | `/v1/learn` | Uloží success pattern |
| `POST` | `/v1/recall` | Najde relevantní patterny |
| `POST` | `/v1/compose` | Sestaví pipeline |
| `POST` | `/v1/evaluate` | Multi-eval scoring |
| `POST` | `/v1/aging` | Spustí pattern aging (decay + prune) |
| `POST` | `/v1/feedback/decay` | Spustí feedback decay |
| `POST` | `/v1/evolve` | Vygeneruje vylepšený prompt |
| `POST` | `/v1/analyze-failures` | Seskupí failure patterny |
| `POST` | `/v1/skills/register` | Registruje skill tagy na pattern |
| `POST` | `/v1/skills/search` | Vyhledá patterny dle skill tagů |
| `GET` | `/v1/feedback` | Top recurring feedback |
| `GET` | `/v1/metrics` | Statistiky |
| `GET` | `/v1/health` | Health check + storage type |
| `DELETE` | `/v1/patterns/{key}` | Smaže pattern |

### Příklady

```bash
# Learn
curl -X POST http://localhost:8000/v1/learn \
  -H "Content-Type: application/json" \
  -d '{"task": "Parse CSV", "code": "import csv", "eval_score": 8.5}'

# Recall
curl -X POST http://localhost:8000/v1/recall \
  -H "Content-Type: application/json" \
  -d '{"task": "Read CSV and compute averages", "limit": 3}'

# Metrics
curl http://localhost:8000/v1/metrics

# Health
curl http://localhost:8000/v1/health
```

### Autentizace

```bash
# Set keys
BRAIN_API_KEYS=my-secret-key docker compose up

# Use key
curl -H "Authorization: Bearer my-secret-key" http://localhost:8000/v1/metrics
```

### Bezpečnostní konfigurace

| Proměnná | Default | Popis |
|----------|---------|-------|
| `BRAIN_CORS_ORIGINS` | `*` | Povolené CORS origins (doporučeno omezit v produkci) |
| `BRAIN_RATE_LIMIT_DEFAULT` | `60` | Max požadavků/min pro standardní endpointy |
| `BRAIN_RATE_LIMIT_EXPENSIVE` | `10` | Max požadavků/min pro LLM-intensive endpointy |
| `BRAIN_MAX_BODY_SIZE` | `1048576` | Max velikost request body v bytech (1 MB) |

---

## PostgreSQL storage

Spuštění s pgvector backendou:

```bash
# 1. Uncomment pgvector service in docker-compose.yml

# 2. Spuštění
BRAIN_STORAGE=postgres \
BRAIN_DATABASE_URL=postgresql://brain:brain@pgvector:5432/brain \
docker compose up

# 3. Aplikace migrací (první spuštění)
docker compose exec brain-api alembic upgrade head
```

Nebo bez Dockeru:

```bash
pip install "agent-brain[openai,postgres]"

from agent_brain.providers.postgres import PostgresStorage
storage = PostgresStorage(database_url="postgresql://...")
brain = Brain(embeddings=OpenAIEmbeddings(), storage=storage, llm=OpenAIProvider())
```

---

## Konfigurace providerů

### OpenAI (doporučeno)

```python
import os
os.environ["OPENAI_API_KEY"] = "sk-..."

from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

brain = Brain(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
    storage=JSONStorage(path="./brain_data"),
)
```

### Jen embeddings, bez LLM

```python
brain = Brain(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
    llm=None,  # default
)

brain.learn(...)    # ✅ funguje
brain.recall(...)   # ✅ funguje
brain.evaluate(...) # ❌ ProviderError: evaluate() requires llm=...
```

---

## CLI

```bash
# Instalace
pip install "agent-brain[cli]"

# Inicializace
agent-brain init --path ./brain_data

# Spuštění REST API serveru
agent-brain serve --host 0.0.0.0 --port 8000

# Metriky a statistiky
agent-brain status --path ./brain_data

# Sémantické vyhledávání
agent-brain recall "Parse CSV and compute statistics" --limit 5

# Pattern aging (decay + prune)
agent-brain aging --path ./brain_data
```

---

## Architektura

```
agent_brain/
├── brain.py             # Brain facade (public API)
├── types.py             # Pydantic modely
├── _util.py             # Shared utility
│
├── core/                # Interní stores
│   ├── success_patterns.py   # Aging, reuse boost
│   ├── eval_store.py         # Eval history + quality multiplier
│   ├── eval_feedback.py      # Feedback clustering + decay
│   ├── metrics.py            # Run statistics
│   └── skill_registry.py     # Capability-based pattern tagging
│
├── reuse/               # Reuse engine
│   ├── matcher.py            # Semantic search + eval weighting
│   ├── composer.py           # LLM pipeline decomposition
│   └── contracts.py          # Data-flow validation + cycle detection
│
├── eval/
│   └── evaluator.py          # MultiEvaluator (concurrent, median, variance)
│
├── providers/
│   ├── base.py               # ABC: LLMProvider, EmbeddingProvider, StorageBackend
│   ├── openai.py             # OpenAI LLM + embeddings
│   ├── anthropic.py          # Anthropic/Claude LLM provider
│   ├── local_embeddings.py   # sentence-transformers (no API key)
│   ├── json_storage.py       # JSON storage (thread-safe, atomic writes)
│   └── postgres.py           # PostgreSQL + pgvector
│
├── api/                 # REST API (Phase 2)
│   ├── app.py                # App factory, env var konfigurace
│   ├── routes.py             # Endpointy
│   ├── auth.py               # Bearer token middleware
│   ├── deps.py               # Dependency injection
│   └── schemas.py            # API modely
│
├── db/                  # Database (Phase 2)
│   ├── models.py             # SQLAlchemy modely
│   └── migrations/           # Alembic
│
├── evolution/           # Prompt evolution + failure clustering (Phase 3)
│   ├── prompt_evolver.py    # LLM-based prompt improvement
│   └── failure_cluster.py   # Failure pattern clustering
│
├── sdk/                 # Framework integrations (Phase 3)
│   ├── langchain.py         # LangChain BrainCallback
│   └── webhook.py           # Lightweight HTTP SDK client
│
├── exceptions.py        # Custom exception hierarchy (BrainError, ProviderError, ...)
│
└── cli/                 # CLI tool (Typer + Rich)
```

---

## Stav implementace

| Komponenta | Stav |
|------------|------|
| `brain.learn()` | ✅ |
| `brain.recall()` | ✅ |
| `brain.evaluate()` | ✅ |
| `brain.compose()` | ✅ |
| `brain.get_feedback()` | ✅ |
| `brain.run_aging()` | ✅ |
| `brain.delete_pattern()` | ✅ |
| `brain.evolve_prompt()` | ✅ Phase 3 |
| `brain.analyze_failures()` | ✅ Phase 3 |
| `brain.register_skills()` / `find_by_skills()` | ✅ Phase 3 |
| `brain.metrics` | ✅ |
| `brain.export()` / `brain.import_data()` | ✅ Phase 4 |
| Custom exception hierarchy | ✅ Phase 4 |
| OpenAI provider | ✅ |
| Anthropic provider | ✅ Phase 3 |
| Local embeddings (sentence-transformers) | ✅ Phase 3 |
| JSON storage (thread-safe) | ✅ |
| REST API (FastAPI) — 14 endpoints | ✅ Phase 2+3+4 |
| PostgreSQL + pgvector | ✅ Phase 2 |
| Docker + docker-compose | ✅ Phase 2 |
| LangChain BrainCallback | ✅ Phase 3 |
| Webhook SDK client | ✅ Phase 3 |
| CLI (Typer + Rich) | ✅ Phase 4 |
| CrewAI plugin | Post-launch |

---

## Vývoj a testování

```bash
# Instalace pro vývoj
pip install -e ".[dev,openai]"

# Spuštění testů
pytest

# S coverage reportem
pytest --cov=agent_brain --cov-report=term-missing
```

Testy nevyžadují API klíče — používají `FakeEmbeddings` (deterministické vektory z MD5 hashe) a mockovaný LLM. FastAPI testy používají `TestClient` z httpx.

---

## Původ

Extrahováno z Agent Factory V2 — self-improving AI agent factory.
Factory zůstává jako open-source referenční implementace, která dokazuje, že Brain funguje v praxi.
