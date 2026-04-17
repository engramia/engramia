# MCP Server

Engramia can run as an **MCP server** (Model Context Protocol), connecting directly to Claude Desktop, Cursor, Windsurf, or VS Code Copilot.

## Installation

```bash
pip install "engramia[openai,mcp]"
```

## Running

```bash
engramia-mcp
```

The server runs over **stdio transport** — MCP clients launch it as a subprocess automatically.

## Client configuration

### Claude Desktop

Config file location:

- **Linux/macOS:** `~/.config/claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "engramia": {
      "command": "engramia-mcp",
      "env": {
        "ENGRAMIA_DATA_PATH": "/path/to/engramia_data",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

### Cursor / Windsurf

Use the same JSON format in the IDE's MCP server settings.

## Available tools

| Tool | Description |
|------|-------------|
| `brain_learn` | Store a run result as a success pattern |
| `brain_recall` | Find relevant patterns for a new task (semantic search) |
| `brain_evaluate` | N independent LLM evaluations, median + variance |
| `brain_compose` | Decompose a task into a validated multi-agent pipeline |
| `brain_feedback` | Get recurring quality issues for prompt injection |
| `brain_metrics` | Statistics (runs, success rate, pattern count, reuse rate) |
| `brain_aging` | Run time-based decay + prune stale patterns |

## Configuration

The MCP server uses the same environment variables as the REST API:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (postgres mode only) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |

## Usage example

Once configured, you can ask Claude Desktop / Cursor to use Engramia tools directly:

> "Use brain_learn to store this successful code with eval_score 8.5"

> "Use brain_recall to find patterns similar to 'parse CSV and compute statistics'"

> "Use brain_metrics to show current memory statistics"

The MCP tools accept the same parameters as the Python API — see [API Reference](../api-reference.md) for details.
