# Provider failover chain (Business+)

A failover chain is an ordered list of fallback credentials that the
runtime tries when the primary credential's call fails with a transient
error (5xx, timeout, network, rate limit). The chain is per-credential —
your OpenAI credential can fall back to Anthropic, your Anthropic
credential can fall back to a different OpenAI key, etc.

> **Tier**: Business or Enterprise.

## What triggers failover

Engramia classifies provider exceptions into two buckets:

| Bucket | Examples | Behaviour |
|--------|----------|-----------|
| **Auth-class** | `AuthenticationError`, `BadRequestError`, `PermissionDeniedError`, Gemini 4xx | **Fail fast** — never failover. Surfaces rotation/revocation immediately. |
| **Transient** | 5xx, timeouts, network errors, rate limits | **Failover** — try next credential in chain. |

This split is deliberate. Failing over on an auth error would mask the
signal that the tenant needs to re-validate their key, and could
inadvertently widen access via a different credential's scopes.

## Chain shape

- **Max length**: primary + 2 fallbacks = 3 chain steps total.
- **Order matters**: the runtime tries entries left-to-right.
- **Same tenant only**: cross-tenant references are rejected at the API
  layer with a 422 (defence in depth — `tenant_credentials.id` is a
  UUID, but we check the WHERE clause instead of trusting that).
- **Active only at PATCH time**: a credential being revoked or marked
  invalid is rejected when you set the chain. Run-time degradation
  (a fallback turning inactive after the chain was set) is silently
  skipped — the chain becomes one shorter.
- **No self-reference**: 422 `FAILOVER_CHAIN_INVALID` if the chain
  contains the credential's own id.
- **No duplicates**: each id may appear at most once.

## API

### Read

The current chain is part of the credential's public view:

```http
GET /v1/credentials/{id}
```

```json
{
  "id": "cred-abc123",
  "provider": "openai",
  ...
  "failover_chain": ["cred-anthropic-key", "cred-gemini-fallback"],
  "updated_at": "2026-04-29T12:34:56.789Z"
}
```

The `updated_at` field is the **ETag basis** for the next write — capture
it before opening an edit form.

### Write — full replace

```http
PATCH /v1/credentials/{id}/failover-chain
Content-Type: application/json
If-Match: "2026-04-29T12:34:56.789Z"

{"failover_chain": ["cred-anthropic-key", "cred-gemini-fallback"]}
```

**Semantics:**

- The body **replaces** the entire chain. Send `[]` to disable failover.
- `If-Match` is **mandatory** — same lost-update protection as
  per-role routing.
- Validation runs in this order:
  1. Body shape (max length, no duplicates, valid id format)
  2. Self-reference check (`{id}` not in chain)
  3. Per-entry tenant + active-status lookup
  4. Tier gate (only when chain is non-empty)
  5. ETag check
  6. Apply update + invalidate caches + audit log

  Self-ref is checked **before** the tier gate so a tenant trying to set
  a structurally invalid chain gets the real reason (422), not a
  misleading "upgrade your plan" (402).

### Permission

Only **owner** and **admin** roles
(permission string `credentials:failover_chain:write`).

### Errors

| HTTP | `error_code` | When |
|------|--------------|------|
| `402` | `ENTITLEMENT_REQUIRED` | Tier below Business with a non-empty chain |
| `403` | `FORBIDDEN` | Caller lacks `credentials:failover_chain:write` |
| `412` | `PRECONDITION_FAILED` | `If-Match` does not match current `updated_at` |
| `422` | `FAILOVER_CHAIN_INVALID` | Self-ref / unknown id / inactive credential |
| `422` | `VALIDATION_ERROR` | Bad shape (length, duplicates, id format) |
| `428` | `PRECONDITION_REQUIRED` | `If-Match` header missing |
| `404` | `CREDENTIAL_NOT_FOUND` | Credential id unknown for this tenant |

## Combined with per-role routing

Each chain member resolves its **own** `role_models` map independently.
Example: primary OpenAI maps `eval -> gpt-4.1-mini`; the Anthropic
fallback maps `eval -> claude-haiku-4-5`. When OpenAI is down and the
runtime falls over, the call uses `claude-haiku-4-5`, not the Anthropic
credential's `default_model`.

This means **set the same logical roles on every credential in the
chain** if you want consistent cost/quality after failover. Otherwise
the fallback silently uses the credential-wide default.

## Telemetry

```
engramia_llm_failover_total{fallback_position="1"}   # primary failed, secondary used
engramia_llm_failover_total{fallback_position="2"}   # primary + secondary failed
```

Use these counters to detect a primary provider outage. If
`fallback_position="1"` rate spikes for one tenant, their primary key is
having issues; if it spikes globally, the upstream provider is down.

## Cache & invalidation

The chain is built once per `(tenant_id, primary_provider, role)` and
cached. PATCHing **any** credential in the chain invalidates the
tenant-level cache, so the next call rebuilds with the new chain shape.
Cross-credential references are tracked implicitly through the
tenant-scoped flush.

## Downgrade behaviour

Same as per-role routing: the configured chain stays active after a
downgrade, but you can no longer edit it until you upgrade. Empty-list
clear is always allowed.

## Related

- [per-role-routing.md](per-role-routing.md) — per-role model mapping
- [../architecture/credentials.md](../architecture/credentials.md) — full BYOK architecture
- [../runbooks/llm-provider-outage.md](../runbooks/llm-provider-outage.md) — when failover does not save you
