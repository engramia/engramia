# CLI

Engramia includes a CLI tool built with Typer and Rich.

## Installation

```bash
pip install "engramia[cli]"
```

## Commands

### init

Initialize a new Engramia data directory.

```bash
engramia init --path ./engramia_data
```

### serve

Start the REST API server.

```bash
engramia serve --host 0.0.0.0 --port 8000
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Port |

### status

Show memory metrics and statistics.

```bash
engramia status --path ./engramia_data
```

Displays: pattern count, total runs, success rate, average eval score, reuse count.

### recall

Semantic search for patterns from the command line.

```bash
engramia recall "Parse CSV and compute statistics" --limit 5
```

| Option | Default | Description |
|--------|---------|-------------|
| `--limit` | `5` | Max results to return |

### aging

Run pattern aging (decay + prune).

```bash
engramia aging --path ./engramia_data
```

Applies 2%/week decay and removes patterns with score < 0.1.

### reindex

Re-embed all stored patterns with the current embedding provider. Use after changing models.

```bash
engramia reindex --path ./engramia_data
engramia reindex --dry-run      # preview only
```

## Key Management (`engramia keys`)

Requires `ENGRAMIA_DATABASE_URL` to be set.

### keys bootstrap

Create the first owner API key (one-time, empty `api_keys` table only).

```bash
engramia keys bootstrap --tenant "My Company" --project default
```

### keys create

Create a new API key via the REST API.

```bash
engramia keys create --name "CI key" --role editor --api-key engramia_sk_...
```

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | (required) | Display name |
| `--role` | `editor` | `owner`/`admin`/`editor`/`reader` |
| `--api-key` | env `ENGRAMIA_API_KEY` | Your auth key |
| `--url` | `http://localhost:8000` | API base URL |
| `--max-patterns` | (inherit) | Pattern quota |

### keys list / keys revoke

```bash
engramia keys list --api-key engramia_sk_...
engramia keys revoke KEY_ID --api-key engramia_sk_... --yes
```

## Data Governance (`engramia governance`)

### governance retention

Apply retention policy — delete patterns older than threshold.

```bash
engramia governance retention --days 365 --path ./engramia_data
engramia governance retention --dry-run   # preview only
```

### governance export

Export patterns to NDJSON (GDPR Art. 20).

```bash
engramia governance export --output backup.jsonl
engramia governance export --classification public,internal
```

### governance purge-project

Permanently delete all data for a project (GDPR Art. 17). Irreversible.

```bash
engramia governance purge-project my-project --tenant default --yes
```

## Environment variables

The CLI uses the same environment variables as the REST API. See [Environment Variables](environment-variables.md) for the complete reference.

Key variables for CLI usage:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | Storage backend |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | JSON storage path |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (required for `keys` and `governance purge-project`) |
| `OPENAI_API_KEY` | — | Required for recall (embeddings) |
| `ENGRAMIA_LOCAL_EMBEDDINGS` | — | Use local sentence-transformers instead of OpenAI |
