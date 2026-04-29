# Anthropic — BYOK Setup

Anthropic is the recommended provider for premium-quality `evaluate`
and `evolve`. Default model is `claude-sonnet-4-6`; `claude-opus-4-7`
is significantly more expensive but worth it for high-stakes
evaluations.

> **Anthropic does not offer an embeddings endpoint.** If you choose
> Anthropic as your only credential, Engramia automatically falls back
> to the lightweight local `LocalEmbeddings` (sentence-transformers,
> 384-dim) for `/v1/recall`. For production semantic search at scale,
> add a separate **OpenAI** or **Gemini** credential with
> `purpose=embedding`.

## 1. Create an API key in Anthropic

1. Sign in at [console.anthropic.com](https://console.anthropic.com/settings/keys).
2. **Settings → API Keys → Create Key**.
3. Name it descriptively (e.g. `engramia-prod`).
4. Optional: scope to a specific Workspace if you have multiple.
5. **Copy the key now** — Anthropic shows it exactly once. The key
   begins with `sk-ant-`.

## 2. Set a spending limit

1. **Plans & billing → Spending limit** in the Anthropic console.
2. Set a monthly cap. Anthropic enforces this hard — once you hit it,
   API calls 402 until the next billing cycle starts or you bump the
   cap.

When the limit is reached, Engramia surfaces the 402 to the caller and
marks the credential `invalid` after the first failure. Subsequent
calls fall back to demo mode.

## 3. Add the key in Engramia

In the dashboard:

1. **Settings → LLM Providers → Add provider**.
2. Provider: **Anthropic**.
3. Paste the key (starts with `sk-ant-`).
4. Default model: leave blank to use `claude-sonnet-4-6`, or set
   explicitly:
   - `claude-haiku-4-5` — cheap, fast, good for high-volume `eval`
   - `claude-sonnet-4-6` — default, good balance
   - `claude-opus-4-7` — premium, ~5× the cost of Sonnet
5. Click **Validate & save**. Engramia pings
   `https://api.anthropic.com/v1/models` (5 s timeout).

REST equivalent:

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "anthropic",
    "purpose": "llm",
    "api_key": "sk-ant-...",
    "default_model": "claude-sonnet-4-6"
  }'
```

Note `purpose: "llm"` (not `"both"`) — Anthropic has no embeddings.

## 4. Add an embeddings credential (production)

For real semantic search you need an embeddings provider. Two options:

**OpenAI for embeddings** (recommended — best price/quality):

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "purpose": "embedding",
    "api_key": "sk-...",
    "default_embed_model": "text-embedding-3-small"
  }'
```

**Gemini for embeddings**:

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "gemini",
    "purpose": "embedding",
    "api_key": "AIza...",
    "default_embed_model": "gemini-embedding-001"
  }'
```

Engramia's resolver will use the LLM credential for `/v1/evaluate`
and the embedding credential for `/v1/recall` automatically.

## 5. Per-role routing (Business tier)

```bash
curl -X PATCH https://api.engramia.dev/v1/credentials/{id} \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "role_models": {
      "eval": "claude-haiku-4-5",
      "evolve": "claude-opus-4-7",
      "default": "claude-sonnet-4-6"
    }
  }'
```

Useful pattern: cheap Haiku for `eval` (3× per evaluation), premium
Opus for the rare `evolve` calls.

## Troubleshooting

**400 `category=auth_failed`**
: Anthropic rejected the key. Confirm the key is exact (no leading
  whitespace from the copy/paste) and that the workspace it belongs
  to is still active.

**`recall` returns lower-quality matches than expected**
: You may be using the local 384-dim embeddings fallback. Add an
  OpenAI or Gemini embedding credential per step 4 above and run
  **Settings → Embedding reindex** (Pro+ tier) to rebuild the HNSW
  index with the new dimensionality. See
  [embedding-reindex.md](../embedding-reindex.md).

**Anthropic returns 529 Overloaded**
: The Anthropic API is under temporary load. Engramia retries with
  exponential back-off up to 3 attempts. If all attempts fail, the
  call returns 502 to your client. The credential remains active —
  no need to re-validate.
