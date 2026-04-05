# CLAUDE.md — Engramia

## What is Engramia

Standalone Python library, REST API, and MCP server for **reusable agent execution memory and evaluation**.
Agents don't learn from previous runs — Engramia fixes that.

**Core operations:** Learn → Recall → Compose → Evaluate → Improve

## Architecture (high-level)

```
                        ┌─────────────┐
                        │   Clients   │
                        │ SDK / CLI / ��
                        │ MCP / REST  │
                        └──────┬──────┘
                               │
                   ┌───────────▼───────────┐
                   │  FastAPI + Middleware  │
                   │  (auth, rate-limit,   │
                   │   headers, body-size) │
                   └───────────┬───────────┘
                               │
                   ┌───────────▼───────────┐
                   │     Memory facade     │
                   │  learn / recall /     │
                   │  evaluate / compose   │
                   └──┬────┬────┬────┬─────┘
                      │    │    │    │
              ┌───────▼┐ ┌▼────▼┐ ┌▼────────┐
              │ Stores ││ Eval  ││Providers │
              │patterns││ multi ││ LLM     │
              │feedback││ eval  ││ embed   │
              │metrics ││       ││ storage │
              │skills  ││       ││(JSON/PG)│
              └────────┘└───────┘└─────────┘
```

```
engramia/
├── __init__.py          # Public facade: Memory class + exceptions
├── memory.py             # Memory implementation (wires all stores)
├── types.py             # Pydantic models (incl. Scope, AuthContext)
├── _context.py          # Scope contextvar: get_scope / set_scope / reset_scope
├── _util.py             # Helpers (extract_json_from_llm, jaccard, reuse_tier)
├── _factory.py          # Provider factory from env vars
├── exceptions.py        # EngramiaError hierarchy (incl. QuotaExceededError, AuthorizationError)
├── core/                # Pattern storage, eval, feedback, metrics, skills
├── reuse/               # Semantic search, pipeline composition, contracts
├── eval/                # MultiEvaluator (ThreadPoolExecutor, median, variance >1.5)
├── providers/           # LLM, embedding, storage backends (ABC + implementations)
├── api/                 # FastAPI REST API + auth + middleware
├── db/                  # SQLAlchemy 2.x models + Alembic migrations
├── evolution/           # Prompt evolution + failure clustering
├── sdk/                 # CrewAI, LangChain, webhook integrations
├── cli/                 # Typer CLI (init, serve, status, recall, aging)
├── mcp/                 # MCP server (stdio transport)
├── analytics/           # ROI event collection (ROICollector, rolling 10 k window)
├── jobs/                # DB-backed async job queue (PostgreSQL FOR UPDATE SKIP LOCKED + in-memory fallback)
├── governance/          # Data lifecycle: deletion, export, redaction, retention
└── telemetry/           # Request-id context, structured logging, health, tracing, Prometheus middleware
```

## Conventions

- Provider abstraction via ABC — every new provider implements the base interface
- Storage is pluggable — JSON for dev, Postgres for prod/SaaS
- No hardcoded API keys — env vars or constructor params
- Tests: pytest, `fail_under=80%`
- Type hints on all public APIs
- Google-style docstrings on public functions
- `logging.getLogger(__name__)` — no `print()` in production
- Input validation at the Memory API boundary

## License — important when releasing

File: `LICENSE.txt` (BSL 1.1). On every version bump in `pyproject.toml`:
- **Licensed Work** → new version (e.g. `Engramia, version 0.6.0`)
- **Change Date** → release date + 4 years
- File header date → release date

## Security

OWASP ASVS Level 2/3. See `SECURITY.md` for full details.

## Technologies

Python 3.12+, FastAPI, Typer + Rich, SQLAlchemy 2.x + pgvector, Alembic, OpenAI/Anthropic SDK, Pydantic v2, numpy

## Production

- **VM**: Hetzner CX23, region DE, `root@engramia-staging`
- **API**: `https://api.engramia.dev` (Caddy + Let's Encrypt)
- **Current version**: `v0.6.5`
- Deploy details → `engramia/api/CLAUDE.md`

## Permissions

- Allowed to run bash commands without confirmation
- Allowed to edit and create files without confirmation
- Allowed to run tests and linters without confirmation
- Allowed to run grep, find, ls and all read-only shell commands without confirmation
- Allowed to run ruff, pytest, coverage and other linting/testing tools without confirmation
- All file deletion operations require user confirmation
- All read operations are permitted without confirmation
