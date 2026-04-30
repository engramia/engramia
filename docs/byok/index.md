# Bring Your Own Key (BYOK)

Engramia Cloud uses **your own LLM provider API key** for every evaluation.
You control which provider you use, which model is invoked, and how much
you spend — Engramia stores patterns, runs the multi-evaluator orchestra,
keeps the audit log, and serves the dashboard, but never holds your
billing relationship with OpenAI / Anthropic / Google / Ollama.

This page is a quick orientation. Pick your provider for step-by-step
setup:

| Provider | Best for | Setup guide |
|----------|----------|-------------|
| **OpenAI** | Default. Widest model coverage, native embeddings. | [openai.md](openai.md) |
| **Anthropic** | Premium quality on `evaluate` + `evolve`. No embedding endpoint. | [anthropic.md](anthropic.md) |
| **Google Gemini** | Cheap default + multimodal. Native embeddings. | [gemini.md](gemini.md) |
| **Ollama** | On-prem / air-gap. Use at your own risk in v0.7. | [ollama.md](ollama.md) |
| **OpenAI-compatible** (Together, Groq, Fireworks, vLLM) | Niche providers behind an OpenAI-compatible endpoint. | [openai.md](openai.md) (use `base_url`) |

## How it works

1. You generate an API key in your provider's console (e.g.
   [platform.openai.com/api-keys](https://platform.openai.com/api-keys)).
2. You add the key in Engramia at **Settings → LLM Providers**.
3. Engramia validates the key against the provider's `/models` endpoint
   (5-second timeout). If the provider rejects it, the row is rejected
   with HTTP 400 — no encrypted ciphertext is ever stored for an
   invalid key.
4. On success, Engramia encrypts the key with **AES-256-GCM** and stores
   only the ciphertext + nonce + auth-tag + a 4-character display
   fingerprint (e.g. `sk-...abcd`). The plaintext is never returned by
   any API or shown again.
5. Every subsequent `/v1/evaluate`, `/v1/recall`, `/v1/compose`, etc.
   resolves the active tenant's credential and forwards the call to
   the right concrete provider with your key.

For the full architecture, see
[architecture/credentials.md](../architecture/credentials.md).

## Multiple credentials per tenant

You can have at most one credential per `(provider, purpose)` pair. The
`purpose` field has three values:

- `llm` — used for generation calls (`/v1/evaluate`, `/v1/compose`,
  `/v1/evolve`).
- `embedding` — used for semantic-search embeddings
  (`/v1/learn`, `/v1/recall`).
- `both` — used for both LLM and embedding when the provider supports
  both (OpenAI, Gemini, Ollama).

Common setups:

- **OpenAI for everything**: one credential, `provider=openai`,
  `purpose=both`.
- **Anthropic for LLM, OpenAI for embeddings**: two credentials,
  `(anthropic, llm)` + `(openai, embedding)`. Anthropic does not offer
  embeddings; the resolver handles this fall-back automatically.
- **Gemini for everything**: one credential, `provider=gemini`,
  `purpose=both`. The default model is `gemini-2.5-flash` (cheap); set
  `default_model` to `gemini-2.5-pro` if you want premium quality.

## Business-tier features

Two BYOK extensions are gated to the Business and Enterprise plans:

- [**Per-role model routing**](per-role-routing.md) — map each agent
  role (`eval`, `architect`, `coder`, `evolve`) to a different model on
  the same credential. Run cheap/fast for evaluation, premium for
  evolution.
- [**Provider failover chain**](failover-chain.md) — fall back to a
  secondary credential (different provider, even) when the primary
  hits a transient error. Auth errors fail fast; transients failover.

Both are edited via dedicated `PATCH /v1/credentials/{id}/role-models`
and `PATCH /v1/credentials/{id}/failover-chain` endpoints. They share
the same admin-only permission gate, mandatory `If-Match` ETag, and
audit-log shape — see the per-feature pages for details.

## Demo mode

If you skip adding a key (or your key gets revoked at the provider
side), Engramia falls back to **demo mode**: the LLM endpoints return
deterministic placeholder responses with a clear "DEMO MODE — add your
LLM key" feedback message. The recall path still works using local
embeddings (sentence-transformers) so you can explore the dashboard.

The demo cap is **50 calls per tenant per calendar month**. Past 50
calls in a month, `/v1/evaluate` returns HTTP 429 with a hint to add a
real key.

## Per-role model routing (Business tier)

On the Business tier and above you can pin a different model per
logical role. Example: cheap `gpt-4.1-mini` for `eval` (Engramia
runs 3 of these in parallel for every evaluation), premium
`claude-opus-4-7` for `evolve` (rare but high-stakes).

This is configured via the `role_models` field on the credential
(JSON object: `{"eval": "gpt-4.1-mini", "evolve": "claude-opus-4-7"}`).
The role values Engramia uses internally:

- `eval` — multi-evaluator scoring
- `coder` — code generation in `compose`
- `architect` — high-level decomposition in `compose`
- `evolve` — prompt evolution
- `default` — anything else

Lower tiers use the credential's `default_model` for every role.

## Cost expectations

Because you bring your own key, the cost is whatever your provider
charges. Engramia adds **no markup**. Rough order-of-magnitude:

- **Multi-evaluator** (`/v1/evaluate`, default `num_evals=3`): one
  evaluation runs 3 LLM calls in parallel against the same prompt.
- **Recall** (`/v1/recall`): one embedding call per query, no LLM.
- **Compose** (`/v1/compose`): one LLM call to decompose, then a recall
  per stage.
- **Evolve** (`/v1/evolve`): two LLM calls per iteration (candidate +
  scorer); typically 3-5 iterations.

Set hard cost ceilings in your provider's console
(OpenAI: Settings → Limits → Usage limits;
Anthropic: Console → Plans & billing → Spending limit;
Google: Cloud Console → Billing → Budgets) — Engramia honours their
4xx responses by marking the credential `invalid` and falling back to
demo mode rather than retrying.

## Security

Engramia's credential storage uses authenticated encryption (AES-GCM)
with per-record nonces and AAD bound to `(tenant_id, provider, purpose)`
so that swapping ciphertext between tenants fails the GCM tag check.
The master key (`ENGRAMIA_CREDENTIALS_KEY`) lives only in the
operator's environment, SOPS-encrypted at rest. Even a full database
dump is useless without the master key.

For the full threat model and key-rotation procedure, see
[architecture/credentials.md](../architecture/credentials.md).
