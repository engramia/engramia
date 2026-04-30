# Per-role cost ceiling (Business+)

Per-role cost ceilings put a monthly $ cap on each role override. When a
role's spend reaches the cap in the current UTC month, Engramia falls
back to the credential's `default_model` for that role until the
calendar month rolls. Service continuity wins over rigid caps — there is
no `429 Too Many Requests`.

> **Tier**: Business or Enterprise. Companion to
> [per-role-routing.md](per-role-routing.md) — ceilings only apply to
> roles you have already mapped to a non-default model.

## Why

Per-role routing makes it easy to map a busy role like `coder` to a
premium model. A coding agent that misbehaves in a tight loop can burn
through several thousand dollars before the operator notices. The
ceiling is a **safety net** between BYOK budget and the real provider
bill — when the cap is reached, the role degrades to your default model
(usually a cheaper one) instead of continuing to escalate cost.

Three properties of the design:

1. **No 429.** The runtime keeps serving requests; only the model
   selection changes. From the agent's perspective the API stays up.
2. **Per role, not per credential.** Each role has its own counter
   (`(tenant, credential, role, month)` is the PK), so an `eval` cap
   does not freeze a `coder` role.
3. **Default model not protected.** If a role has no override, the
   ceiling does not apply — the call would already use `default_model`.
   Setting a ceiling on the credential's chosen baseline does not make
   sense; that is the tenant's deliberate default.

## API

### Read

```http
GET /v1/credentials/{id}
```

Returns `role_cost_limits` plus the credential's `updated_at`.

```json
{
  "id": "cred-abc123",
  "role_models": {"coder": "claude-opus-4-7"},
  "role_cost_limits": {"coder": 5000},
  "updated_at": "2026-04-30T08:42:11.456Z"
}
```

`role_cost_limits` is `{role: monthly_cap_in_cents}`. Above example caps
the `coder` role at $50 / month.

### Write — full replace

```http
PATCH /v1/credentials/{id}/role-cost-limits
Content-Type: application/json
If-Match: "2026-04-30T08:42:11.456Z"

{"role_cost_limits": {"coder": 5000, "evolve": 20000}}
```

**Semantics:**

- The body **replaces** the entire map. Send `{}` to clear all ceilings.
- `If-Match` **mandatory**. Same lost-update protection as the per-role
  routing endpoint.
- Values are **integer cents**. Positive only — to remove a ceiling, omit
  the role from the body or send `{}` to clear all.
- Hard upper bound at $100 000 / month / role. Anything higher is
  rejected as a likely dollars-vs-cents typo (`50_000_000` cents = $500k).
- Role names are server-normalised to lowercase; same regex as
  `role_models`.
- Cap of 16 entries.

### Permission

Owner / admin only — `credentials:role_cost_limits:write`. Editor-tier
keys cannot touch billing-impact knobs.

### Errors

| HTTP | `error_code` | When |
|------|--------------|------|
| `402` | `ENTITLEMENT_REQUIRED` | Tier below Business with a non-empty body |
| `403` | `FORBIDDEN` | Caller lacks `credentials:role_cost_limits:write` |
| `412` | `PRECONDITION_FAILED` | `If-Match` does not match current `updated_at` |
| `422` | `VALIDATION_ERROR` | Negative / zero / too-large value, > 16 entries, bad role name |
| `428` | `PRECONDITION_REQUIRED` | `If-Match` header missing |
| `404` | `CREDENTIAL_NOT_FOUND` | Credential id unknown for this tenant |

## What gets metered

Every successful LLM call against a credential triggers a post-call
write to the spend counter:

```
spend_cents += rate_cards.cost_for(provider, model, tokens_in, tokens_out)
```

Token counts come from each provider SDK's `usage` field
(OpenAI `prompt_tokens` / `completion_tokens`, Anthropic
`input_tokens` / `output_tokens`, Gemini `usage_metadata`). The rate
card is a static map in
[`engramia/billing/rate_cards.py`](https://github.com/engramia/engramia/blob/main/engramia/billing/rate_cards.py),
reviewed quarterly against the providers' public pricing pages.

**Providers without a rate card** — Ollama, openai_compat with custom
endpoints — bypass the gate. The runtime logs an INFO when it cannot
find an entry; the call proceeds at full price. Tenants on those
providers are responsible for their own observability.

## Preflight gate

Before each LLM call, the wrapper checks:

```
if role in cred.role_models and role in cred.role_cost_limits:
    spend = role_meter.get_spend(tenant, cred, role, current_month)
    if spend >= cred.role_cost_limits[role]:
        effective_role = "default"  # use default_model for this call
```

The check is one DB read per call (cached in PostgreSQL — `(tenant,
cred, role, month)` is the PK so the lookup is sub-millisecond). The
hot-path overhead is negligible vs. the LLM call itself.

**Fail-open**: if the meter read raises (DB blip), the call is allowed
to proceed with the original role. One over-budget call is a cheaper
failure than blocking traffic on a transient DB issue.

## Telemetry

```
engramia_role_ceiling_fallback_total{role}   # increment on each fallback
```

Counter — when this rate spikes for a tenant, their primary cap is
being hit regularly. Combine with the ROI analytics rollups to compare
per-role spend across months.

The audit log captures both the **edit** event (`credential_role_cost_limits_updated`
with a structured added/removed/changed diff) and the **runtime**
event (`ROLE_CEILING_EXCEEDED` log line at WARNING with tenant /
credential / role / spend / cap). Loki retention preserves the full
history.

## Downgrade behaviour

Identical to per-role routing and failover chain: configured ceilings
remain active after a tier downgrade, but you cannot edit them until
you upgrade back. Empty-clear is always allowed.

## Interaction with failover chain

The ceiling fires **before** the failover chain is built — the swap is
to `default_model` on the same credential, not to the next chain entry.
Failover is for transient errors; the ceiling is for budget. Both can
be active on the same credential without interfering.

## Rate card maintenance

The rate card is updated quarterly. When prices change:

1. Bump the constant in `engramia/billing/rate_cards.py`.
2. Update `RATE_CARD_REVIEWED` to today.
3. Mirror the change in `Dashboard/src/lib/rate-cards.ts`.
4. Add a CHANGELOG entry — past spend is **not** retroactively re-costed,
   but operators auditing a historical bill spike need to know which
   card was current at the time.

## Related

- [per-role-routing.md](per-role-routing.md) — the role mapping the
  ceiling protects
- [failover-chain.md](failover-chain.md) — orthogonal fault-tolerance
  feature
- [../architecture/credentials.md](../architecture/credentials.md) — full
  BYOK architecture
