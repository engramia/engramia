# CLI

Engramia includes a CLI tool built with Typer and Rich.

## Installation

```bash
pip install "engramia[cli]"
```

## Commands

### init

Initialize a new brain data directory.

```bash
engramia init --path ./brain_data
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
engramia status --path ./brain_data
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
engramia aging --path ./brain_data
```

Applies 2%/week decay and removes patterns with score < 0.1.

## Environment variables

The CLI uses the same environment variables as the REST API:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | Storage backend |
| `ENGRAMIA_DATA_PATH` | `./brain_data` | JSON storage path |
| `OPENAI_API_KEY` | — | Required for recall (embeddings) |
