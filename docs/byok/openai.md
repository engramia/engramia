# OpenAI — BYOK Setup

OpenAI is Engramia's default provider. It covers both LLM (Chat
Completions) and embeddings (`text-embedding-3-small`) with one key,
and works as the engine for any OpenAI-compatible endpoint
(Together, Groq, Fireworks, vLLM, Azure OpenAI) via the optional
`base_url` field.

## 1. Create an API key in OpenAI

1. Sign in at [platform.openai.com](https://platform.openai.com/api-keys).
2. Go to **API keys → Create new secret key**.
3. Give the key a recognisable name (e.g. `engramia-prod`) so you can
   identify it later in audit logs.
4. Optional: scope the key to a single OpenAI project for blast-radius
   isolation.
5. **Copy the key now** — OpenAI shows it exactly once. If you lose it,
   delete it and create a new one.

## 2. Set a hard spending cap (recommended)

Engramia uses your key as-is and does not enforce any cost limit. Set
your own ceiling at the provider before adding the key:

1. **Settings → Billing → Limits** in the OpenAI dashboard.
2. Set both the **Hard limit** (calls fail past this) and a lower
   **Soft limit** (email warning).

If OpenAI returns HTTP 429 (rate-limited) or 402 (over quota), Engramia
surfaces the error to the caller without retrying. Past the hard
limit, evaluations fall back to demo mode automatically.

## 3. Add the key in Engramia

In the dashboard:

1. Go to **Settings → LLM Providers**.
2. Click **Add provider**.
3. Provider: **OpenAI**.
4. Paste the key into the **API key** field. The field is type=password
   and never echoed back.
5. Optional: set **Default model** (defaults to `gpt-4.1`). Common
   alternatives: `gpt-4.1-mini` for cheap eval, `gpt-5` for premium.
6. Click **Validate & save**. Engramia pings
   `https://api.openai.com/v1/models` with your key (5-second timeout)
   and stores the encrypted key only on success.

Or via REST API:

```bash
curl -X POST https://api.engramia.dev/v1/credentials \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "purpose": "both",
    "api_key": "sk-proj-...",
    "default_model": "gpt-4.1"
  }'
```

The response contains the credential metadata but **not** the
plaintext key — keep your own copy.

## 4. Verify

After saving, run a smoke test from the dashboard:

1. **Patterns → Recall** with any query. The first call may take a few
   seconds (cold embedding cache) and should return real results.
2. **Evaluations → Run evaluation** on a sample task. The response
   should include real `feedback` text rather than the demo-mode
   placeholder.

## 5. Rotation

To rotate a key:

1. Generate a new key in the OpenAI dashboard.
2. In Engramia, **Settings → LLM Providers → Add provider** with the
   same provider+purpose. The new key replaces the old one (UPSERT)
   and the audit log records both fingerprints.
3. Delete the old key in the OpenAI dashboard.

## OpenAI-compatible endpoints

If you want to point Engramia at Together, Groq, Fireworks, Azure
OpenAI, or a self-hosted vLLM, choose **OpenAI-compatible** in the
provider dropdown and set **Base URL**. Engramia uses the OpenAI SDK
against that endpoint.

| Provider | Base URL example | Notes |
|----------|------------------|-------|
| Azure OpenAI | `https://your-resource.openai.azure.com` | Per-deployment routing |
| Together | `https://api.together.xyz/v1` | Many open models |
| Groq | `https://api.groq.com/openai/v1` | Sub-second inference |
| Fireworks | `https://api.fireworks.ai/inference/v1` | Mixed open + tuned models |
| vLLM (self-hosted) | `http://your-vllm:8000/v1` | DIY deployment |

The default model field still applies — set it to whatever model your
endpoint exposes.

## Models and roles (Business tier)

On Business and above you can pin a model per role. Set this via PATCH:

```bash
curl -X PATCH https://api.engramia.dev/v1/credentials/{id} \
  -H "Authorization: Bearer engramia-prod-..." \
  -H "Content-Type: application/json" \
  -d '{
    "role_models": {
      "eval": "gpt-4.1-mini",
      "evolve": "gpt-5",
      "default": "gpt-4.1"
    }
  }'
```

`eval` runs 3× per evaluation by default — using a cheaper model here
typically saves 60-80 % on evaluation cost without measurable quality
loss.

## Troubleshooting

**400 `category=auth_failed`**
: OpenAI rejected the key. Most common cause is a typo; less common is
  a key whose project no longer exists.

**400 `category=unreachable`**
: The validation ping timed out (5 s). Try again — likely a transient
  OpenAI issue. The key is **not** stored on this path.

**Demo-mode banner reappears after adding a key**
: Force-refresh the dashboard. The credentials list cache TTL is
  60 seconds and the resolver invalidates immediately on save, but the
  banner reads from a separate query.

**`evaluate` returns "DEMO MODE — add your LLM key" feedback**
: The key was saved but Engramia is in demo fallback because the row's
  status is `invalid`. Check **Settings → LLM Providers → row → "error: ..."**
  for the provider's error message. Common cause: the key was revoked
  externally; rotate via the steps above.
