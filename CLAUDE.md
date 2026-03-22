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

```
agent_brain/
├── core/               # Jádro: patterns, evaluations, embeddings, metrics, skills
├── reuse/              # Reuse engine: matching, composition, contract validation
├── eval/               # Evaluation: multi-eval scoring, feedback, model routing
├── evolution/          # Self-improvement: prompt evolution, failure analysis, aging
├── providers/          # Abstrakce: LLM, Embedding, Storage (OpenAI, Claude, JSON, Postgres)
├── db/                 # SQLAlchemy modely + Alembic migrace (součást package)
├── api/                # REST API (FastAPI)
├── sdk/                # Python SDK + pluginy (LangChain, CrewAI)
└── cli/                # CLI tool (Typer)
```

### Provider abstrakce

Brain je **model-agnostic** a **storage-agnostic**:

- **LLM**: OpenAI, Anthropic, libovolný provider implementující `LLMProvider` ABC
- **Embeddings**: OpenAI (`text-embedding-3-small` jako default), lokální modely (sentence-transformers). Rozšiřitelné přes `EmbeddingProvider` ABC — další providery (Voyage AI, Cohere, apod.) lze přidat jako optional dependency.
- **Storage**: JSON soubory (single-machine) nebo PostgreSQL + pgvector (SaaS). Storage abstrakce zahrnuje vector search (`search_similar(embedding, limit)`) — JSON backend dělá brute-force cosine similarity, Postgres využívá pgvector index.

### Klíčové koncepty

- **Success patterns** — Úspěšné agent designy s time-based decay (2%/týden). Automatické zapomínání zastaralého.
- **Eval feedback injection** — Recurring quality issues se automaticky injektují do coder promptu.
- **Contract validation** — Pipeline stages deklarují reads/writes. Brain validuje, že data flow je konzistentní.
- **Multi-eval scoring** — N nezávislých LLM evaluací, median agregace, variance detection (>1.5 = warning).
- **Semantic agent search** — Task-based embeddings pro přesné vyhledávání podobných agentů.
- **Pattern aging** — Staré patterny přirozeně klesají na skóre, nové je vytlačují.
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

# Recall
matches = brain.recall(task="Read CSV and calculate averages", limit=5)

# Compose pipeline
pipeline = brain.compose(task="Fetch stock data, analyze, write report")

# Evaluate
result = brain.evaluate(task=task, code=code, output=stdout)

# Feedback for prompt injection
feedback = brain.get_feedback(task_type="csv", limit=4)
```

### Jako REST API

```bash
docker run -p 8000:8000 agent-brain
```

```
POST /learn      — zaznamenej výsledek běhu
GET  /recall     — najdi relevantní agenty
POST /compose    — navrhni pipeline
POST /evaluate   — multi-eval scoring
GET  /feedback   — top feedback patterns
GET  /routing    — model routing doporučení
```

### Jako LangChain plugin

```python
from agent_brain.sdk.langchain import BrainCallback

chain = LLMChain(llm=llm, prompt=prompt, callbacks=[BrainCallback(brain)])
# Brain se automaticky učí z každého chain run
```

## Původ

Extrahováno z Agent Factory V2 — self-improving AI agent factory.
Factory zůstává jako open-source referenční implementace, která dokazuje, že Brain funguje.

## Technologie

- Python 3.12+
- FastAPI (REST API)
- SQLAlchemy 2.x + pgvector (optional Postgres backend)
- OpenAI / Anthropic SDK (provider-agnostic)
- Pydantic (data validation)

## Konvence

- Provider abstrakce přes ABC — každý nový provider implementuje base interface
- Storage je pluggable — JSON pro dev/single-machine, Postgres pro SaaS
- Žádné hardcoded API klíče — vše přes env vars nebo konstruktor
- Testy pro každý modul — pytest, fail_under=80%
- Type hints na všech public API
- Docstrings na public functions (Google style)

## Klíčové soubory

| Soubor | Účel |
|--------|------|
| `roadmap.md` | Implementační roadmapa (5 fází) |
| `agent_brain/__init__.py` | Public API surface (Brain class) |
| `agent_brain/types.py` | Pydantic modely — Match, EvalResult, Pattern, Pipeline, ... |
| `agent_brain/providers/base.py` | ABC pro LLM, Embedding, Storage (vč. vector search) |
