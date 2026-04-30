# Ollama — BYOK Setup

> **Status: supported** as of Phase 6.6 #4 (2026-04-29). Engramia validates
> the configured `default_model` against the Ollama server's pulled-model
> list at credential-create time, surfaces available models to the
> dashboard via a 1 h-cached `/api/tags` snapshot, and auto-sizes the
> per-call timeout based on the model's parameter count
> (60 s for 1 B, 120 s for 7 B, 600 s for 70 B, default 300 s when
> the param size is unknown).

Ollama runs LLMs locally on your hardware (CPU or GPU). It's the right
choice for:

- **Air-gapped deployments** — your data never leaves your network.
- **Latency-insensitive batch workloads** — Ollama is slow on CPU but
  free of API costs.
- **Compliance-extreme tenants** — combine with the self-hosted
  Engramia deployment.

It is **not** a good fit for production multi-tenant cloud workloads —
the per-call latency on CPU is measured in seconds, not milliseconds.

## 1. Run Ollama

If you don't already have it:

```bash
# macOS
brew install ollama
ollama serve &

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (this is what Engramia will call)
ollama pull llama3.3
ollama pull nomic-embed-text  # if you want embeddings via Ollama
```

By default Ollama listens on `http://localhost:11434`. Engramia talks
to its OpenAI-compatible endpoint at `http://localhost:11434/v1`.

## 2. Make Ollama reachable from Engramia

Engramia in **cloud mode** runs in a separate process from your local
Ollama. Three deployment patterns:

**A. Self-hosted Engramia + local Ollama** (most common)
: Both run on the same host. Use `base_url=http://localhost:11434/v1`.

**B. Engramia in Docker, Ollama on host**
: Use `base_url=http://host.docker.internal:11434/v1` on macOS/Windows,
  or `http://172.17.0.1:11434/v1` on Linux.

**C. Engramia in cloud, Ollama behind a tunnel**
: You expose Ollama via Tailscale, ngrok, Cloudflare Tunnel, or a
  reverse proxy. The endpoint should require **at least basic auth** —
  Ollama itself does not authenticate.

> **Security note:** never expose Ollama directly to the public
> internet without auth. The endpoint accepts arbitrary inference
> requests and any caller can run arbitrary inference on your hardware
> (resource exhaustion + potential prompt-injection attack surface).

## 3. Add the credential in Engramia

In the dashboard:

1. **Settings → LLM Providers → Add provider**.
2. Provider: **Ollama (use at your own risk)**.
3. **Base URL**: the URL where Engramia can reach Ollama
   (e.g. `http://localhost:11434/v1`).
4. **API key**: leave the default placeholder `ollama` unless you've
   fronted Ollama with a reverse proxy that requires a real bearer
   token.
5. **Default model**: name of an installed Ollama model
   (e.g. `llama3.3`, `qwen2.5-coder`, `deepseek-r1`).
6. Click **Validate & save**. The validation ping calls
   `${base_url}/models` — Ollama returns the list of installed models;
   Engramia accepts any 2xx response.

REST equivalent:

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "ollama",
    "purpose": "llm",
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1",
    "default_model": "llama3.3"
  }'
```

## 4. Embeddings (optional)

Not all Ollama models support embeddings. The standard choice is
`nomic-embed-text` (768-dim) or `mxbai-embed-large` (1024-dim). Pull
it first, then add a separate `purpose=embedding` credential:

```bash
ollama pull nomic-embed-text
```

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "ollama",
    "purpose": "embedding",
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1",
    "default_embed_model": "nomic-embed-text"
  }'
```

If you change embedding model dimension, see
[embedding-reindex.md](../embedding-reindex.md).

## 5. Performance tuning

Ollama on CPU is *slow*. Engramia's per-LLM-call timeout for Ollama
defaults to **5 minutes** to accommodate cold-load + warmup. For
production-ish use:

- Run Ollama on a GPU host. A single A4000 / RTX 4090 typically gets
  you 30-100 tok/s on 7-13B models.
- Pre-load models on Ollama startup (`OLLAMA_KEEP_ALIVE=24h`) so the
  first request after a long idle doesn't pay the cold-load tax.
- Use smaller models for `eval` (it runs 3× per evaluation): a
  Qwen 2.5 0.5B or Llama 3.2 1B is often "good enough" for the eval
  judge role.

## 6. Recommended models (as of 2026-04)

| Use | Model | Notes |
|-----|-------|-------|
| General LLM | `llama3.3` | 70B; needs serious GPU |
| Coder | `qwen2.5-coder` | 7B / 32B variants |
| Reasoning | `deepseek-r1` | Strong CoT, slower |
| Embeddings | `nomic-embed-text` | 768-dim, fast |
| Embeddings (premium) | `mxbai-embed-large` | 1024-dim |

Pull whichever you want with `ollama pull <name>`.

## Known limitations

- **No streaming** — Engramia uses sync calls, you don't get
  token-by-token output.
- **No tool/function calling validation** — Ollama supports it on
  newer models but Engramia doesn't introspect; you may get silent
  no-ops on older models.
- **Hot-reload requires manual refresh** — when you `ollama pull` a
  new model, the model-list cache holds the previous snapshot for up
  to 1 h. Click "Refresh models" in the dashboard to bypass the cache,
  or wait the TTL out. Validation against the new model still works
  immediately because re-validating a credential always hits
  `/api/tags` fresh.
- **Connection pool** — the openai SDK's default pool of 10 may be
  too high for a single-GPU Ollama; reduce `ENGRAMIA_LLM_CONCURRENCY=2`
  on the Engramia side.

## Troubleshooting

**400 `category=unreachable`**
: Engramia can't reach the URL. Check that Ollama is running
  (`ollama ps`) and that the URL is reachable from the Engramia
  process (curl from inside the container if dockerised).

**400 `category=config` — "no models pulled"**
: Your Ollama server is reachable but has zero models installed.
  Run `ollama pull <model>` on the server, then re-validate the
  credential.

**400 `category=model_missing`**
: The `default_model` you configured isn't pulled on the server.
  The error message includes up to 8 of the available model names
  so you can pick one or run `ollama pull <correct-name>`.

**400 `category=auth_failed` with `ollama` placeholder**
: You fronted Ollama with auth and forgot to update the credential.
  Use the real bearer token in the **API key** field.

**Long timeouts (90s+) on first call**
: Ollama is loading the model into VRAM. Set
  `OLLAMA_KEEP_ALIVE=24h` to keep it loaded; subsequent calls will
  be much faster.

**"model not found" errors at runtime (not validation)**
: The `default_model` was valid at credential-create time, but
  someone ran `ollama rm` on the server since then. Re-validate the
  credential via the dashboard (or `POST /v1/credentials/{id}/validate`)
  to surface the missing-model state.
