# Per-role model routing (Business+)

Per-role routing lets you map each Engramia agent role to a different model
on the same provider — for example, run cheap-and-fast `gpt-4.1-mini` for
multi-evaluator scoring and reserve `claude-opus-4-7` for the prompt
evolver. Engramia routes every internal LLM call through a logical role
hint, and the credential's `role_models` map decides which concrete model
the SDK is invoked with.

> **Tier**: Business or Enterprise. Pro/Team/Developer plans use the
> credential's single `default_model` for every role.

## When this is useful

- **Cost shaping** — eval calls are short, frequent, and tolerant of a
  smaller model. Keep `gpt-4.1` (or `claude-sonnet-4-6`) for `architect`
  + `evolve`, drop `eval` to `gpt-4.1-mini` and pay 5× less for the
  largest call volume.
- **Latency tuning** — pin `coder` to a fast model for interactive flows;
  let `architect` take the latency hit on its (rarer) decomposition pass.
- **Quality gates** — only the prompt evolver gets the premium model;
  everything else stays on the default tier.

## Canonical roles

| Role | Where it's emitted | Suggestion |
|------|-------------------|------------|
| `default` | Anything without an explicit role | Your provider's mainline model |
| `eval` | `MultiEvaluator.evaluate` (per-call scoring inside `/v1/evaluate`) | Cheap & fast — `gpt-4.1-mini`, `claude-haiku-4-5`, `gemini-2.5-flash` |
| `architect` | `PipelineComposer._decompose` + `PromptEvolver.evolve` planner | Quality — `gpt-4.1`, `claude-sonnet-4-6` |
| `coder` | Final code synthesis after decomposition | Strong code model — `gpt-4.1`, `claude-sonnet-4-6` |
| `evolve` | `PromptEvolver.evolve_with_eval` candidate execution | Quality — same as `architect` is fine |
| `recall` | Reserved for future hybrid-recall LLM rerank | Currently unused — set if you have a strong opinion |

Custom role names (Enterprise) are accepted — the validator only enforces
the regex `^[a-z][a-z0-9_]{0,31}$`. The dashboard's autocomplete suggests
the canonical six; anything else is free-form.

## API

### Read

```http
GET /v1/credentials/{id}
```

Returns `role_models` plus the credential's `updated_at` timestamp. That
timestamp is the **ETag basis** for the next write — capture it before
opening an edit form.

### Write — full replace

```http
PATCH /v1/credentials/{id}/role-models
Content-Type: application/json
If-Match: "{updated_at as ISO-8601}"

{"role_models": {"eval": "gpt-4.1-mini", "architect": "claude-opus-4-7"}}
```

**Semantics:**

- The body **replaces** the entire mapping. Send `{}` to clear all
  overrides; send `{"eval": "x"}` and the previous `architect` mapping
  is dropped.
- `If-Match` is **mandatory**. Missing returns `428 PRECONDITION_REQUIRED`,
  stale returns `412 PRECONDITION_FAILED` so you can re-read and retry
  without losing a concurrent edit by another admin.
- Role names are server-normalised to lowercase. `"Eval"` is stored as
  `"eval"` so the hot-path JSONB key match cannot silently miss because
  of a casing typo.
- Model names are validated against `^[A-Za-z0-9._:/-]{1,128}$` — wide
  enough for OpenAI/Anthropic canonical IDs and OpenAI-compatible
  endpoints with custom identifiers (`models/together/llama-3.3-70b`).
- Hard cap: **16 entries** per credential. The canonical role list is
  six; sixteen leaves Enterprise plenty of room for custom roles without
  blowing up the provider cache cardinality.

### Permission

Only **owner** and **admin** roles can edit `role_models`
(permission string `credentials:role_models:write`). Editor-tier API
keys can still rotate the underlying credential via `POST /v1/credentials`
but cannot change the cost-impact routing on it.

### Errors

| HTTP | `error_code` | When |
|------|--------------|------|
| `402` | `ENTITLEMENT_REQUIRED` | Tier below Business with a non-empty body |
| `403` | `FORBIDDEN` | Caller lacks `credentials:role_models:write` |
| `412` | `PRECONDITION_FAILED` | `If-Match` does not match current `updated_at` |
| `422` | `VALIDATION_ERROR` | Invalid role/model name, > 16 entries |
| `428` | `PRECONDITION_REQUIRED` | `If-Match` header missing |
| `404` | `CREDENTIAL_NOT_FOUND` | Credential id unknown for this tenant |

## Resolution order

When a code path issues an LLM call with `role="X"`, Engramia resolves the
model in this precedence:

1. `role_models["X"]` — explicit per-role override
2. `default_model` — credential-wide default (set on `POST` or main `PATCH`)
3. The provider-wide static fallback (e.g. `gpt-4.1` for OpenAI)

A partially populated map works as you would expect — `eval` has its
override, `architect` falls through to `default_model`. Setting only the
roles you care about is the recommended pattern.

## Telemetry

Per-role calls are labeled in Prometheus:

```
engramia_llm_call_duration_seconds{provider="openai", model="gpt-4.1-mini", role="eval"}
```

`role` is intentionally **not** combined with `tenant_id` as a label —
that would push series count out of comfort range. For per-tenant cost
breakdowns, query the ROI analytics rollups in `engramia/analytics/`.

## Downgrade behaviour

If your subscription drops below Business, your existing `role_models`
configuration **stays active** — the hot path does not check tier on
every call. You will:

- Continue to use the routing you set up while you were on Business.
- See a yellow banner in the dashboard prompting you to either upgrade
  back or clear the configuration.
- Be unable to **edit** the mapping until you upgrade. The empty-clear
  request (`{"role_models": {}}`) is always allowed regardless of tier
  so you have a clean exit.

If you want a hard reset, send `PATCH /v1/credentials/{id}/role-models`
with `{"role_models": {}}` and an `If-Match` matching the current
`updated_at`.

## Related

- [failover-chain.md](failover-chain.md) — provider failover (also Business+)
- [../architecture/credentials.md](../architecture/credentials.md) — full BYOK architecture
