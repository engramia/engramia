# MCP Server

Engramia speaks the **Model Context Protocol** (MCP) over two transports:

- **stdio** (default, self-host) — every tier, runs as a local subprocess.
  Suitable for Claude Desktop / Cursor / Windsurf installed on the
  developer's machine.
- **Streamable HTTP** (hosted, Engramia Cloud) — Team tier and above. No
  local install; the MCP client connects directly to
  `https://api.engramia.dev/v1/mcp` with a Bearer API key.

Both transports expose the same tools (subject to per-tier filtering on the
hosted side — see [Tools below](#tools)).

## stdio transport (self-host)

### Installation

```bash
pip install "engramia[openai,mcp]"
```

### Running

```bash
engramia-mcp
```

MCP clients launch this binary as a subprocess automatically based on their
config.

### Client configuration

#### Claude Desktop

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

#### Cursor / Windsurf

Use the same JSON format in the IDE's MCP server settings.

## Hosted MCP transport (Engramia Cloud)

> **Tier requirement:** Team plan or higher. Developer and Pro tiers cannot
> open hosted MCP sessions; the cloud returns HTTP 402 Payment Required.

### Why use the hosted transport

- No local Engramia install — the MCP client just needs an HTTP URL and a
  Bearer key. Whole-team rollouts (Claude Desktop deployed to N developers)
  become trivial.
- Centralised pattern store — every team member's `engramia_learn` and
  `engramia_recall` hits the same backing storage as your REST API tenants
  use, so memories stay shared.
- BYOK by default — the LLM keys used for `engramia_evaluate` and
  `engramia_evolve` are the tenant's own (configured in the dashboard
  under Credentials), not Engramia's. You're not paying for Engramia's
  inference budget.

### Concurrent-session limits

Each tenant has a tier-defined cap on concurrent open MCP sessions. Sessions
that go idle for 30 minutes are automatically closed and free a slot.

| Tier | Max concurrent MCP sessions |
|------|------------------------------|
| Developer | — (no access) |
| Pro | — (no access) |
| Team | 5 |
| Business | 25 |
| Enterprise | 100 |

When the cap is reached the cloud returns HTTP 429 with `Retry-After: 60`.

### Client configuration

#### Claude Desktop

```json
{
  "mcpServers": {
    "engramia": {
      "transport": "http",
      "url": "https://api.engramia.dev/v1/mcp",
      "headers": {
        "Authorization": "Bearer ENG_xxx"
      }
    }
  }
}
```

(Exact key names follow your MCP client's config schema; the example above
matches Claude Desktop ≥ build 0.10 which supports HTTP transport. For
older builds, fall back to stdio.)

#### Cursor / Windsurf / IDE plugins

Set the transport to "Streamable HTTP" (or equivalent) and point at
`https://api.engramia.dev/v1/mcp`. The IDE will issue the MCP `initialize`
handshake on startup; Engramia replies with the session ID, which the
client carries on subsequent requests via the `Mcp-Session-Id` header.

### Self-host the hosted transport

If you run Engramia on your own infrastructure and want to expose
Streamable HTTP rather than stdio, set the feature flag:

```bash
ENGRAMIA_MCP_HOSTED_ENABLED=true
ENGRAMIA_MCP_SESSION_IDLE_SECONDS=1800     # 30 min default
ENGRAMIA_MCP_LIMITS_TEAM=5                 # override caps if desired
ENGRAMIA_MCP_LIMITS_BUSINESS=25
ENGRAMIA_MCP_LIMITS_ENTERPRISE=100
```

The `/v1/mcp` route mounts onto the same FastAPI app as the REST API. If
you front Engramia with Caddy/nginx/another reverse proxy, ensure SSE
buffering is disabled on that path — the Caddy snippet below is the
reference:

```caddy
@mcp path /v1/mcp /v1/mcp/*
handle @mcp {
    reverse_proxy {$UPSTREAM_API:engramia-api:8000} {
        flush_interval -1
        transport http {
            response_header_timeout 30m
            read_buffer 8KiB
        }
    }
}
```

## Tools

The catalog is shared by both transports. On hosted MCP it is filtered per
the caller's tier and RBAC role; on stdio it is exposed in full (self-host
is single-tenant).

| Tool | Description | RBAC | Hosted tier |
|------|-------------|------|-------------|
| `engramia_learn` | Store a successful run as a reusable pattern | editor+ | Team+ |
| `engramia_recall` | Semantic search over stored patterns | reader+ | Team+ |
| `engramia_evaluate` | N independent LLM evaluations, median + variance | editor+ | Team+ |
| `engramia_feedback` | Recurring quality issues for prompt injection | reader+ | Team+ |
| `engramia_metrics` | Run/pattern/reuse statistics | reader+ | Team+ |
| `engramia_aging` | Time-decay + prune stale patterns | editor+ | Team+ |
| `engramia_compose` | Decompose a task into a multi-agent pipeline (experimental) | editor+ | Business+ |
| `engramia_evolve` | Generate an improved system prompt from failure feedback | editor+ | Business+ |
| `engramia_analyze_failures` | Cluster recurring failure feedback into systemic issues | editor+ | Business+ |

The hosted transport returns only the tools the caller is allowed to use
in `tools/list` responses. Tools below the caller's tier are not surfaced
at all (to keep the MCP client UI free of permanent "upgrade required"
chrome). Discoverability for paywall upsell happens in the dashboard.

## Configuration

Both transports use the same environment variables as the REST API:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENGRAMIA_STORAGE` | `json` | `json` or `postgres` |
| `ENGRAMIA_DATA_PATH` | `./engramia_data` | Path for JSON storage |
| `ENGRAMIA_DATABASE_URL` | — | PostgreSQL URL (postgres mode only) |
| `ENGRAMIA_LLM_PROVIDER` | `openai` | LLM provider |
| `ENGRAMIA_LLM_MODEL` | `gpt-4.1` | Model ID |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ENGRAMIA_MCP_HOSTED_ENABLED` | `false` | Mount hosted Streamable HTTP transport at `/v1/mcp` |
| `ENGRAMIA_MCP_SESSION_IDLE_SECONDS` | `1800` | Hosted session idle timeout |
| `ENGRAMIA_MCP_LIMITER_BACKEND` | `inmemory` | `inmemory` (default) or `redis` (planned) |
| `ENGRAMIA_MCP_LIMITS_TEAM` | `5` | Max concurrent hosted sessions for Team-tier tenants |
| `ENGRAMIA_MCP_LIMITS_BUSINESS` | `25` | Same, Business |
| `ENGRAMIA_MCP_LIMITS_ENTERPRISE` | `100` | Same, Enterprise |

## Usage example

Once configured, you can ask Claude Desktop / Cursor to use Engramia tools directly:

> "Use engramia_learn to store this successful code with eval_score 8.5"

> "Use engramia_recall to find patterns similar to 'parse CSV and compute statistics'"

> "Use engramia_metrics to show current memory statistics"

The MCP tools accept the same parameters as the Python API — see
[API Reference](../api-reference.md) for details.
