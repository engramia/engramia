# Google Gemini — BYOK Setup

Gemini is the cheapest of Engramia's first-party providers and offers
both LLM (`gemini-2.5-flash` / `gemini-2.5-pro`) and embeddings
(`gemini-embedding-001`) under one key. Default LLM model is
`gemini-2.5-flash` for cost reasons.

## 1. Create an API key in Google AI Studio

1. Sign in at [aistudio.google.com](https://aistudio.google.com/app/apikey).
2. Click **Get API key → Create API key**.
3. Pick the Google Cloud project you want billing to land on
   (Gemini API requires a billing-enabled project for paid models;
   `gemini-2.5-flash` has a generous free tier).
4. Copy the key. Gemini keys begin with `AIza`.

> **Note:** This guide is for the Gemini Developer API (AI Studio).
> Vertex AI Gemini uses a different auth flow (service account JSON +
> ADC) that Engramia does not currently support — vote for it on the
> roadmap if you need it.

## 2. Set up billing limits

1. **Cloud Console → Billing → Budgets & alerts**.
2. Create a monthly budget for the project.
3. Set an alert at 50 %, 90 %, and 100 % of budget.

Google does not hard-stop API calls when a budget is exceeded — the
budget is informational. To enforce a real cap, disable the API on the
project temporarily; Engramia will see a 403 and fall back to demo
mode.

## 3. Add the key in Engramia

In the dashboard:

1. **Settings → LLM Providers → Add provider**.
2. Provider: **Google Gemini**.
3. Paste the key (starts with `AIza`).
4. Default model: leave blank for `gemini-2.5-flash`, or set:
   - `gemini-2.5-flash` — default, cheapest, 1M-token context
   - `gemini-2.5-pro` — premium, best for complex reasoning
   - `gemini-flash-lite` — even cheaper for high-volume `eval`
5. Click **Validate & save**. Engramia pings the Gemini SDK
   (`models.list`) with a 5-second timeout.

REST equivalent:

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "gemini",
    "purpose": "both",
    "api_key": "AIza...",
    "default_model": "gemini-2.5-flash",
    "default_embed_model": "gemini-embedding-001"
  }'
```

## 4. Embedding dimensionality note

The default `gemini-embedding-001` model produces **3072-dim vectors**
— much larger than OpenAI's `text-embedding-3-small` (1536-dim).
Engramia's pgvector schema fixes the dimension at HNSW DDL time, so
**switching from another embedding model to Gemini requires reindexing
the embedding column**. See [embedding-reindex.md](../embedding-reindex.md)
for the procedure (Pro+ tier).

If you are starting fresh, Gemini embeddings are perfectly fine. If
you already have patterns indexed with OpenAI 1536-dim embeddings,
either:

- Stick with an OpenAI embedding credential (set `purpose=embedding`
  on the OpenAI row, `purpose=llm` on the Gemini row), or
- Run the reindex and accept the disk cost (~2× storage for embeddings).

## 5. Per-role routing (Business tier)

```bash
curl -X PATCH https://api.engramia.dev/v1/credentials/{id} \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "role_models": {
      "eval": "gemini-flash-lite",
      "evolve": "gemini-2.5-pro",
      "default": "gemini-2.5-flash"
    }
  }'
```

## Troubleshooting

**400 `category=auth_failed`**
: Either the key is wrong or the Gemini API isn't enabled on the
  underlying Google Cloud project. Check
  **Cloud Console → APIs & Services → Library → Generative Language API
  → Enable**.

**400 `category=unreachable`**
: AI Studio occasionally rate-limits the `models.list` ping during
  region failovers. Wait a minute and retry.

**Embeddings dimensions mismatch (recall returns 500)**
: You changed the embedding provider without reindexing. See the
  warning in step 4 and run [embedding-reindex.md](../embedding-reindex.md).

**`MAX_TOKENS` errors in eval**
: Gemini 2.5 Flash has an 8k output token default in the SDK; raise
  it explicitly via `default_model` settings if your eval prompts
  routinely exceed that. Engramia caps at 4096 by default, which is
  enough for a structured eval JSON response.
