# Credential Storage Architecture (BYOK)

Engramia v0.7.0 · Classification: Public

> Architecture specification for **Bring Your Own Key (BYOK)** credential storage.
> This document describes how Engramia stores, encrypts, resolves, and audits per-tenant LLM provider credentials.

---

## 1. Goals and non-goals

### Goals

1. **Tenants supply their own LLM provider keys** — Engramia never pays for LLM tokens consumed by a tenant
2. **At-rest encryption** of API keys with master-key separation; no plaintext keys in the database
3. **Multi-provider support** — OpenAI, Anthropic, Google Gemini, Ollama, OpenAI-compatible endpoints (Together/Groq/Fireworks/vLLM)
4. **Per-request resolution** — credentials resolved from the authenticated tenant context, not from process-wide environment variables
5. **Graceful degradation** — when no key is configured, fall back to Demo mode with a clear UX signal instead of failing
6. **Self-hosted parity** — single-tenant self-hosters keep using `OPENAI_API_KEY` env vars; the BYOK layer is opt-in via env flag
7. **Pluggable backend** — local AES-GCM by default; HashiCorp Vault Transit / AWS KMS / GCP KMS / Azure Key Vault available for enterprise

### Non-goals

- **LLM cost metering or budgeting** — that is the provider's billing dashboard concern (Anthropic Console, OpenAI Usage)
- **Key vending** — Engramia does not issue or rotate provider-side keys; tenant manages them in OpenAI/Anthropic/Google consoles
- **Provider failover orchestration** — single primary provider per request; secondary chain is a future Phase 6.6 #2 feature
- **Key sharing across tenants** — keys are strictly tenant-scoped, no cross-tenant reuse
- **Memoising LLM responses to reduce cost** — out of scope (would conflict with non-determinism of `evaluate`)

---

## 2. System overview

```
                       ┌────────────────────────────────────────────┐
  Agent / Dashboard    │              TRUST BOUNDARY                │
  ──────HTTPS─────────▶│  Caddy (TLS 1.3)                           │
                       │       │                                    │
                       │       ▼                                    │
                       │  FastAPI (auth, rate-limit, body-size)     │
                       │       │                                    │
                       │       ▼                                    │
                       │  Scope contextvar (tenant_id, project_id)  │
                       │       │                                    │
                       │       ▼                                    │
                       │  Memory facade ── make_llm() ──┐           │
                       │                                │           │
                       │                                ▼           │
                       │                    CredentialResolver      │
                       │                          │                 │
                       │           ┌──────────────┼──────────────┐  │
                       │           │              │              │  │
                       │           ▼              ▼              ▼  │
                       │     LRU cache       CredentialStore    Demo│
                       │     (provider       (DB + decrypt)    Provider│
                       │      instances)         │              (no key)│
                       │           │             ▼              │  │
                       │           │      AESGCMCipher          │  │
                       │           │             │              │  │
                       │           │             ▼              │  │
                       │           │      tenant_credentials    │  │
                       │           │      (encrypted_key,       │  │
                       │           │       nonce, auth_tag)     │  │
                       │           │             │              │  │
                       │           ▼             │              ▼  │
                       │   OpenAI/Anthropic/Gemini/Ollama       Demo│
                       │   Provider instance (api_key resolved)  output│
                       │           │                            │  │
                       └───────────┼────────────────────────────┘  │
                                   │                               │
                                   ▼                               │
                       ┌────────────────────┐                      │
                       │  LLM provider API  │ ◀── tenant's quota   │
                       │  (HTTPS outbound)  │                      │
                       └────────────────────┘                      │
                                                                   │
                       ENGRAMIA_CREDENTIALS_KEY (env, SOPS) ───────┘
                       Master key for AES-GCM decryption
```

**Critical invariants:**

- Master key (`ENGRAMIA_CREDENTIALS_KEY`) lives only in the operator's environment (SOPS-encrypted on disk, never in DB)
- `tenant_credentials` rows contain ciphertext + nonce + auth tag — useless without master key
- Provider instances are cached **per `(tenant_id, role)`**, never globally
- Cache is invalidated on credential update via `CredentialStore.invalidate(tenant_id)`

---

## 3. Threat model

| Threat | Mitigation |
|---|---|
| **Database dump leak** | Keys stored as AES-256-GCM ciphertext. Without `ENGRAMIA_CREDENTIALS_KEY` (only in operator env), ciphertext is opaque. AAD `{tenant_id}:{provider}:{purpose}` prevents record substitution between tenants. |
| **Master key leak from env** | Operator rotates master key → re-encrypt batch via Alembic migration; old `key_version` rows are decrypted and re-saved with new version. Old master key is destroyed. |
| **Backup leak (pg_dump)** | Backups inherit ciphertext-only storage. Master key is **not** in DB → backup alone is not exploitable. Backups are encrypted at rest (Hetzner Storage Box) as a second layer. |
| **Cross-tenant key access via API bug** | `CredentialStore` queries always include `WHERE tenant_id = :scope_tenant_id` from contextvar. Authorization is at the boundary — `require_auth` sets scope before any handler runs. Test suite has `test_cross_tenant_isolation.py` that asserts no leakage. |
| **Insider threat (Engramia operator reading keys)** | Local backend: operator with both DB access AND `ENGRAMIA_CREDENTIALS_KEY` env can decrypt. Mitigated by separation: DB credentials and credentials master key live in separate SOPS files with separate audit logs (`Ops/secrets/.env.prod.enc` vs `Ops/secrets/credentials-key.enc`). Vault backend: operator never sees plaintext, only Vault Transit decrypt API does. |
| **Key replay via stolen Bearer token** | Bearer token rotation, revocation via `DELETE /v1/keys/{id}`, 60s TTL cache window. Tenant should rotate the LLM provider key (in their OpenAI/Anthropic console) if Engramia API key is compromised — Engramia cannot rotate provider-side keys for them. |
| **Memory dump while process running** | Plaintext keys exist only inside `OpenAIProvider`/`AnthropicProvider` instance attributes during a request. Python does not zero memory on object destruction; this is a known acceptable risk vs Vault transit, which would require an HTTPS round-trip per request. Vault backend mitigates this for Enterprise tier. |
| **Side-channel: timing of "key valid?" checks** | `validator.py` uses constant-time comparison; provider validation pings (`/models` endpoint) are rate-limited to 1/min per tenant to avoid amplification attacks. |
| **Demo mode abuse (free LLM via shared infra)** | `DemoMeter` enforces hard cap (50 calls/month per tenant). Demo responses are deterministic mocks, not real LLM calls — Engramia spends $0 on Demo. |
| **Logging leak** | Audit log records `key_fingerprint` (`sk-...abcd`, last 4 chars) only. Plaintext keys never enter logs, exception traces, or telemetry. Pre-commit hook checks for `OPENAI_API_KEY=sk-` patterns in code/configs. |

---

## 4. Data model

### Database schema (Alembic migration `023_tenant_credentials`)

```sql
CREATE TABLE tenant_credentials (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             TEXT NOT NULL REFERENCES cloud_users(tenant_id) ON DELETE CASCADE,
    provider              TEXT NOT NULL,          -- openai | anthropic | gemini | ollama | openai_compat
    purpose               TEXT NOT NULL,          -- llm | embedding | both
    encrypted_key         BYTEA NOT NULL,         -- AES-256-GCM ciphertext
    nonce                 BYTEA NOT NULL,         -- 12 bytes (96 bits, GCM standard)
    auth_tag              BYTEA NOT NULL,         -- 16 bytes (GCM tag)
    key_version           SMALLINT NOT NULL DEFAULT 1,  -- master key rotation marker
    key_fingerprint       TEXT NOT NULL,          -- "sk-...abcd" — last 4 chars for UI display
    base_url              TEXT,                   -- non-null for ollama / openai_compat
    default_model         TEXT,                   -- e.g. "gpt-4.1" — overridable per request
    default_embed_model   TEXT,                   -- e.g. "text-embedding-3-small"
    role_models           JSONB,                  -- Business+ tier: {"eval": "gpt-4.1-mini", "evolve": "claude-opus-4-7"}
    status                TEXT NOT NULL DEFAULT 'active',  -- active | revoked | invalid
    last_used_at          TIMESTAMPTZ,
    last_validated_at     TIMESTAMPTZ,
    last_validation_error TEXT,                   -- nullable; populated when status=invalid
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by            TEXT NOT NULL,          -- cloud_users.id of creator
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_tenant_credentials_provider_purpose
    ON tenant_credentials (tenant_id, provider, purpose);

CREATE INDEX ix_tenant_credentials_tenant ON tenant_credentials (tenant_id);
CREATE INDEX ix_tenant_credentials_status ON tenant_credentials (status) WHERE status != 'active';
```

**Why `purpose` separately from `provider`:**
A tenant may want OpenAI for embeddings (`text-embedding-3-small` is best-in-class) but Anthropic for LLM (Claude Sonnet for `evaluate`). The `(provider, purpose)` UNIQUE constraint allows two rows: `(openai, embedding)` and `(anthropic, llm)`.

**Why `role_models` is JSONB and not a separate table:**
Per-role routing is a Business-tier feature that adds at most 5 entries per credential (`eval`, `coder`, `architect`, `evolve`, `default`). A separate table adds a join with no benefit; JSONB queryable via `->>` operator if ever needed.

### Pydantic models (`engramia/credentials/models.py`)

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

ProviderType = Literal["openai", "anthropic", "gemini", "ollama", "openai_compat"]
PurposeType = Literal["llm", "embedding", "both"]
StatusType = Literal["active", "revoked", "invalid"]


class TenantCredential(BaseModel):
    """In-memory representation of a tenant credential row.

    The plaintext api_key is populated only after CredentialResolver decrypts;
    serialisation excludes it (Pydantic field exclude=True).
    """

    id: str
    tenant_id: str
    provider: ProviderType
    purpose: PurposeType
    api_key: str = Field(exclude=True)              # plaintext, never serialised
    key_fingerprint: str
    base_url: str | None = None
    default_model: str | None = None
    default_embed_model: str | None = None
    role_models: dict[str, str] = Field(default_factory=dict)
    status: StatusType = "active"
    last_used_at: datetime | None = None
    last_validated_at: datetime | None = None

    def model_for_role(self, role: str) -> str:
        """Resolve the model name for a logical role, falling back to default."""
        return self.role_models.get(role) or self.default_model or _PROVIDER_DEFAULT_MODELS[self.provider]


class CredentialCreate(BaseModel):
    """API input — POST /v1/credentials body."""

    provider: ProviderType
    purpose: PurposeType
    api_key: str = Field(min_length=8, max_length=512)
    base_url: str | None = None  # required for ollama / openai_compat
    default_model: str | None = None


class CredentialPublicView(BaseModel):
    """API output — what /v1/credentials returns (no plaintext key).

    Pydantic regenerates this from TenantCredential without api_key
    via model_dump(exclude={"api_key"}).
    """

    id: str
    provider: ProviderType
    purpose: PurposeType
    key_fingerprint: str
    base_url: str | None
    default_model: str | None
    status: StatusType
    last_used_at: datetime | None
    last_validated_at: datetime | None
    created_at: datetime
```

---

## 5. Encryption design

### Cipher choice: AES-256-GCM

| Property | Value | Rationale |
|---|---|---|
| Algorithm | AES-256-GCM | NIST-approved AEAD, widely audited, hardware-accelerated (AES-NI) |
| Key size | 256 bits | Meets PCI-DSS / HIPAA / FedRAMP at-rest requirements |
| Nonce size | 96 bits (12 bytes) | GCM standard; random per record (never reused with same key) |
| Auth tag size | 128 bits (16 bytes) | GCM standard |
| AAD (additional authenticated data) | `f"{tenant_id}:{provider}:{purpose}".encode()` | Prevents an attacker who swaps `encrypted_key` between rows from passing decryption |

**Library:** `cryptography>=42` (already a dependency for `cloud_auth.py` JWT). No new deps.

```python
# engramia/credentials/crypto.py — pseudokód
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

class AESGCMCipher:
    def __init__(self, master_key: bytes, key_version: int = 1) -> None:
        if len(master_key) != 32:
            raise ValueError("Master key must be 32 bytes (256 bits)")
        self._aesgcm = AESGCM(master_key)
        self.key_version = key_version

    def encrypt(self, plaintext: str, aad: bytes) -> tuple[bytes, bytes, bytes]:
        nonce = os.urandom(12)
        ciphertext_with_tag = self._aesgcm.encrypt(nonce, plaintext.encode(), aad)
        # cryptography library returns ciphertext || tag concatenated
        ciphertext, auth_tag = ciphertext_with_tag[:-16], ciphertext_with_tag[-16:]
        return ciphertext, nonce, auth_tag

    def decrypt(self, ciphertext: bytes, nonce: bytes, auth_tag: bytes, aad: bytes) -> str:
        ciphertext_with_tag = ciphertext + auth_tag
        plaintext = self._aesgcm.decrypt(nonce, ciphertext_with_tag, aad)
        return plaintext.decode()
```

### Master key management

| Aspect | Design |
|---|---|
| Storage | Env var `ENGRAMIA_CREDENTIALS_KEY` — base64-encoded 32 bytes |
| Source of truth | SOPS-encrypted `Ops/secrets/credentials-key.enc` (separate from `.env.prod.enc`) |
| Generation | `python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"` |
| Rotation cadence | On compromise, on key custodian change, or yearly best-practice |
| Rotation procedure | Alembic migration `024_rotate_master_key`: read all rows, decrypt with old key, encrypt with new key, increment `key_version`. Atomic per row, idempotent. |
| Backup | Operator MUST back up master key separately from DB backups. Loss of master key = permanent loss of all stored credentials (tenants must re-enter keys). |

### Key version field

Allows zero-downtime rotation:

1. Operator generates new key, sets `ENGRAMIA_CREDENTIALS_KEY_NEW` (in addition to current `ENGRAMIA_CREDENTIALS_KEY`)
2. Engramia binary reads both, decrypts with version match (`key_version = 1` → old key, `key_version = 2` → new key)
3. Background migration re-encrypts all `key_version = 1` rows with new key, sets `key_version = 2`
4. After migration completes, operator drops `ENGRAMIA_CREDENTIALS_KEY` and renames `_NEW` to canonical

---

## 6. Provider abstraction

The existing ABC in `engramia/providers/base.py:18` (`LLMProvider.call(prompt, system, role)`) is unchanged. BYOK changes only **how providers are instantiated** — they take `api_key` as a constructor parameter instead of reading from `os.environ`.

### Existing → BYOK delta

```python
# Before (existing, will be deprecated for cloud mode):
class OpenAIProvider(LLMProvider):
    def __init__(self, model="gpt-4.1", max_retries=3, timeout=30.0):
        # implicitly reads OPENAI_API_KEY from env via openai SDK

# After (BYOK):
class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model="gpt-4.1", base_url: str | None = None,
                 max_retries=3, timeout=30.0):
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
```

`api_key` defaulting to `os.environ.get("OPENAI_API_KEY")` is preserved for **self-hosted single-tenant mode** (`ENGRAMIA_BYOK_ENABLED=false`, see §11).

### New providers

| File | Class | Status |
|---|---|---|
| `providers/gemini.py` | `GeminiProvider`, `GeminiEmbeddings` | NEW — Google Gen AI SDK |
| `providers/ollama.py` | `OllamaProvider` (subclass of `OpenAIProvider`) | NEW — `base_url=http://host:11434/v1`, longer timeouts, `Authorization: Bearer ollama` placeholder |
| `providers/openai_compat.py` | `OpenAICompatProvider` (subclass) | NEW — generic for Together/Groq/Fireworks/vLLM with custom `base_url` |
| `providers/demo.py` | `DemoProvider`, `DemoEmbeddings` | NEW — deterministic mocked responses, used when no credential exists |

All implement existing `LLMProvider` / `EmbeddingProvider` ABCs without modification.

---

## 7. Per-request resolution flow

```
HTTP request arrives
    │
    ▼
require_auth (existing dependency)
    │
    ├── extracts Bearer token / OIDC JWT / cloud JWT
    ├── resolves AuthContext(tenant_id, project_id, role)
    └── set_scope(Scope(tenant_id, project_id))   # contextvar
    │
    ▼
Route handler (e.g., POST /v1/evaluate)
    │
    ▼
Memory.evaluate(...) → MultiEvaluator(num_evals=3)
    │
    ▼
For each of 3 concurrent evaluations:
    │
    ▼
LLMProvider.call(prompt, system, role="eval")
    │
    │  ↑ This LLMProvider instance was injected at Memory construction.
    │    But Memory is built per-request via Depends(get_memory) which calls:
    │
    ▼
get_memory():
    return Memory(
        storage=make_storage(),       # PostgresStorage — scope-filtered
        embeddings=make_embeddings(), # local or BYOK embed provider
        llm=make_llm(),               # ← THE BYOK ENTRYPOINT
    )
    │
    ▼
make_llm():
    scope = get_scope()                                    # contextvar
    return _build_llm_for_tenant(scope.tenant_id, role="default")
    │
    ▼
_build_llm_for_tenant(tenant_id, role) [LRU cached, 512 entries]:
    cred = CredentialResolver.resolve(tenant_id, purpose="llm")
    if cred is None:
        return DemoProvider()
    return _construct_provider(cred, role)
    │
    ▼
CredentialResolver.resolve(tenant_id, purpose="llm"):
    row = CredentialStore.get(tenant_id, purpose="llm")
    if row is None or row.status != "active":
        return None
    aad = f"{row.tenant_id}:{row.provider}:{row.purpose}".encode()
    api_key_plaintext = AESGCMCipher(_master_key).decrypt(
        row.encrypted_key, row.nonce, row.auth_tag, aad
    )
    CredentialStore.touch_last_used(row.id)   # async, fire-and-forget
    return TenantCredential(api_key=api_key_plaintext, **row_fields)
    │
    ▼
_construct_provider(cred, role):
    model = cred.model_for_role(role)
    if cred.provider == "openai":
        return OpenAIProvider(api_key=cred.api_key, model=model, base_url=cred.base_url)
    if cred.provider == "anthropic":
        return AnthropicProvider(api_key=cred.api_key, model=model)
    if cred.provider == "gemini":
        return GeminiProvider(api_key=cred.api_key, model=model)
    if cred.provider == "ollama":
        return OllamaProvider(api_key="ollama", base_url=cred.base_url, model=model)
    if cred.provider == "openai_compat":
        return OpenAIProvider(api_key=cred.api_key, base_url=cred.base_url, model=model)
    raise ProviderError(f"unknown provider: {cred.provider}")
```

### LRU cache details

| Aspect | Value |
|---|---|
| Cache key | `(tenant_id, role)` |
| Cache value | Provider instance (holds plaintext api_key in memory) |
| Size | 512 entries (≈ 100 active tenants × 5 roles) |
| TTL | None — invalidation is event-driven via `CredentialStore.invalidate(tenant_id)` |
| Invalidation triggers | `POST /v1/credentials`, `DELETE /v1/credentials/{id}`, `PATCH /v1/credentials/{id}` |
| Implementation | `functools.lru_cache` wrapped with custom invalidation (`cache_clear` for the specific key) |

**Why no TTL:** TTL would force re-decryption every N minutes for active tenants, increasing CPU load. Event-driven invalidation is correct because credentials only change via tenant action, which we capture.

---

## 8. Demo mode

When `CredentialResolver.resolve()` returns `None`, `make_llm()` returns a `DemoProvider`. This applies to:

- New tenants who skipped "Add LLM key" in onboarding
- Tenants whose key was revoked or marked invalid
- Self-hosted single-tenant deployments without env keys (developer mode)

### `DemoProvider` behaviour

```python
class DemoProvider(LLMProvider):
    DEMO_RESPONSES = {
        "eval": json.dumps({
            "task_alignment": 7, "code_quality": 7, "workspace_usage": 7,
            "robustness": 6, "overall": 6.8,
            "feedback": "DEMO MODE — add your LLM API key in Settings → LLM Providers to get real evaluations."
        }),
        "default": "DEMO RESPONSE — add your LLM API key in Settings → LLM Providers to enable real LLM features."
    }

    def call(self, prompt: str, system: str | None = None, role: str = "default") -> str:
        scope = get_scope()
        if not DemoMeter.try_increment(scope.tenant_id):
            raise QuotaExceededError(
                "Demo mode quota exhausted (50 calls/month). "
                "Add your LLM API key to continue."
            )
        return self.DEMO_RESPONSES.get(role, self.DEMO_RESPONSES["default"])
```

### `DemoMeter`

| Aspect | Value |
|---|---|
| Backing store | New table `demo_call_meter (tenant_id, year_month, count)` — or reuse existing `usage_counters` table |
| Cap | 50 calls/month per tenant |
| Reset | Calendar month boundary (UTC) |
| Failure on cap | `HTTP 429` with `error_code=DEMO_QUOTA_EXCEEDED`, hint to add real key |

### UI signaling

API responses include extra fields when in demo mode:

```json
{
  "median_score": 6.8,
  "variance": 0.0,
  "feedback": "DEMO MODE — ...",
  "_meta": {
    "mode": "demo",
    "demo_calls_used": 12,
    "demo_calls_limit": 50,
    "upgrade_link": "https://app.engramia.dev/settings/llm-providers"
  }
}
```

Dashboard reads `_meta.mode == "demo"` and shows persistent yellow banner: "🟡 Demo mode — eval results are simulated. [Add LLM key]".

---

## 9. API surface

Endpoints live under `/v1/credentials/` (new file `engramia/api/credentials.py`, mounted in `app.py`).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/v1/credentials` | admin+ | Create or replace credential for `(provider, purpose)` |
| `GET` | `/v1/credentials` | admin+ | List all credentials for current tenant (no plaintext) |
| `GET` | `/v1/credentials/{id}` | admin+ | Get single credential metadata (no plaintext) |
| `PATCH` | `/v1/credentials/{id}` | admin+ | Update `default_model`, `role_models`, `base_url` (NOT api_key — use POST to replace) |
| `DELETE` | `/v1/credentials/{id}` | admin+ | Soft-delete (status=`revoked`) — preserves audit trail |
| `POST` | `/v1/credentials/{id}/validate` | admin+ | Ping provider's `/models` endpoint to verify key still works; rate-limited 1/min/tenant |

### Key rules at the API boundary

- `api_key` field is **write-only** — never appears in any response, even to the creator. This forces tenants to store their key in their own password manager, not rely on Engramia as a key vault.
- `POST /v1/credentials` with existing `(tenant_id, provider, purpose)` triple **replaces** the previous row (UPSERT). The previous `key_fingerprint` is logged in audit before replacement.
- `PATCH` cannot change `api_key`. To rotate, the tenant POSTs a new key, which UPSERTs.
- `GET` responses include `key_fingerprint` (`sk-...abcd`) so the tenant can identify which key is active without seeing the plaintext.

### Validation flow

```
POST /v1/credentials
    │
    ▼
1. Pydantic validates input shape
2. Tier gate: provider in {openai, anthropic, gemini, openai_compat} → all tiers
              provider == ollama → all tiers (with ⚠️ "use-at-own-risk" warning header)
3. Optional: synchronous validation ping to provider.list_models()
   - If pings succeeds: status=active
   - If pings fails (401/403): reject with 400 "Invalid API key"
   - If pings is rate-limited or 5xx: status=active anyway, warn user
4. Encrypt with AESGCMCipher
5. INSERT ... ON CONFLICT (tenant_id, provider, purpose) DO UPDATE
6. Invalidate LRU cache for tenant_id
7. Audit log: CREDENTIAL_CREATED with key_fingerprint
8. Return 201 with CredentialPublicView
```

---

## 10. Failure modes

| Scenario | Behaviour |
|---|---|
| Master key env var unset on startup | API refuses to start (`RuntimeError: ENGRAMIA_CREDENTIALS_KEY required when ENGRAMIA_BYOK_ENABLED=true`). Fail fast. |
| Master key wrong (decryption fails) | All LLM calls fall through to `DemoProvider` with a critical-level audit log "MASTER_KEY_DECRYPT_FAILURE". Operator alerts fire. Tenants see degraded service, not data loss. |
| Tenant's key revoked at provider side | First call returns provider's 401 → `CredentialStore.mark_invalid(id, error="401 Unauthorized")` → subsequent calls fall through to `DemoProvider`. Email notification to tenant admin. |
| Tenant's key over quota at provider side | Provider returns 429 → propagate to caller as 502 "LLM provider rate-limited" (do NOT mark credential invalid — quota will reset). |
| Tenant deletes credential mid-request | Cache holds provider instance until current request completes; next request rebuilds → `DemoProvider`. No mid-flight failure. |
| Two tenants share the same plaintext API key | Allowed (Engramia doesn't deduplicate). Each row has independent encryption with own nonce. Provider-side quota is shared (provider's problem, not Engramia's). |
| Credentials table corruption | New tenant requests fall through to demo. Existing cached provider instances continue working until cache eviction. Audit log captures the corruption event. |
| `cryptography` lib InvalidTag (tampering / nonce reuse) | Decryption raises `cryptography.exceptions.InvalidTag` → caught, logged as `CREDENTIAL_TAMPERING_SUSPECTED`, credential marked invalid, security alert fires. Pinpointed by AAD: an attacker swapping rows between tenants would fail tag check immediately. |

---

## 11. Self-hosted vs. cloud mode

BYOK is **opt-in via env flag**. Self-hosted single-tenant deployments shouldn't have to set up master keys, manage credentials tables, or use the dashboard — they already have their key in `OPENAI_API_KEY`.

### Mode selection (`ENGRAMIA_BYOK_ENABLED`)

| Mode | Default | Behaviour |
|---|---|---|
| `false` (self-hosted, default) | when `ENGRAMIA_DATABASE_URL` is unset OR `cloud_users` table is empty | Existing path: `make_llm()` reads `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` from env. `tenant_credentials` table is unused. |
| `true` (cloud) | enabled in `Ops/.env.prod` for `api.engramia.dev` | New path: `make_llm()` resolves per-tenant credential from DB; falls back to `DemoProvider` if no row. Env vars `OPENAI_API_KEY` etc. are ignored at runtime (used only as bootstrap fallback for the `default` tenant in dev/staging). |

### Hybrid mode (Enterprise self-hosted)

Multi-tenant self-hosted instances (rare — only for Enterprise customers running multiple internal product teams as separate tenants) can enable BYOK with a local master key. They are responsible for KMS integration and key rotation; documentation in [Production Hardening](../production-hardening.md).

---

## 12. Migration from current state

Today's state (v0.6.x): single-tenant cloud, server-side `OPENAI_API_KEY` in `Ops/.env.prod` is used for all tenants.

Migration plan:

| Step | Action | Risk |
|---|---|---|
| 1 | Deploy v0.7.0 with `ENGRAMIA_BYOK_ENABLED=false` (no behaviour change) | None — old code path |
| 2 | Run Alembic migration `023_tenant_credentials` (creates table, no data) | None — additive only |
| 3 | Generate master key, store in `Ops/secrets/credentials-key.enc` (SOPS) | None — not yet used |
| 4 | Deploy v0.7.1 with `ENGRAMIA_CREDENTIALS_KEY` set, but `ENGRAMIA_BYOK_ENABLED=false` | None — flag still off |
| 5 | Email all existing tenants (n=0 today, low risk): "Add your LLM key in dashboard before YYYY-MM-DD or your account will switch to demo mode" | UX risk only |
| 6 | After 14-day grace, deploy v0.7.2 with `ENGRAMIA_BYOK_ENABLED=true` | Tenants without keys land in demo mode |
| 7 | Remove `OPENAI_API_KEY` from `Ops/.env.prod` (it's no longer used) | None — clean-up |

**Self-hosters:** unchanged path (ENGRAMIA_BYOK_ENABLED defaults to false). They need to do nothing.

**Existing paying customers:** zero (per `project_byok_strategy.md` memory). Clean break safe.

---

## 13. Audit and observability

### Audit log events

| Event type | When | Detail fields |
|---|---|---|
| `CREDENTIAL_CREATED` | POST /v1/credentials succeeds | provider, purpose, key_fingerprint, base_url, default_model |
| `CREDENTIAL_REPLACED` | POST UPSERT replaces existing | old_key_fingerprint, new_key_fingerprint |
| `CREDENTIAL_DELETED` | DELETE /v1/credentials/{id} | provider, purpose, key_fingerprint |
| `CREDENTIAL_VALIDATED` | POST /v1/credentials/{id}/validate | provider, success |
| `CREDENTIAL_MARKED_INVALID` | First-call provider returned 401/403 | provider, error_message |
| `CREDENTIAL_DECRYPT_FAILURE` | AAD mismatch or cipher tag invalid | row_id, expected_aad |
| `MASTER_KEY_DECRYPT_FAILURE` | Cipher initialised but cannot decrypt any row | sample_row_id |
| `DEMO_MODE_FALLBACK` | First request for tenant with no active credential | tenant_id (rate-limited to 1/hour to avoid log spam) |
| `DEMO_QUOTA_EXCEEDED` | DemoMeter rejects 51st call of the month | tenant_id, calls_used |

All events go to the existing `audit_log` table (per `governance/audit_scrubber.py` retention rules).

### Prometheus metrics

```
engramia_credentials_total{provider, status}            gauge
engramia_credential_resolutions_total{tenant_tier, result}  counter
                                                        result ∈ {hit, miss_demo, miss_invalid, error}
engramia_credential_cache_size                          gauge
engramia_credential_cache_hits_total                    counter
engramia_credential_cache_misses_total                  counter
engramia_demo_calls_total{tenant_tier}                  counter
engramia_master_key_failures_total                      counter
engramia_credential_validation_duration_seconds         histogram
```

### Health probe

Extend `GET /v1/health/deep` with credentials subsystem check:

```json
{
  "credentials": {
    "status": "ok",
    "master_key_loaded": true,
    "active_credentials_count": 142,
    "cache_size": 87
  }
}
```

`status=degraded` if master_key_loaded=false (Engramia running but BYOK broken).

---

## 14. Future extensions

| Extension | Tier | Approach |
|---|---|---|
| **HashiCorp Vault Transit backend** | Enterprise | Replace `AESGCMCipher` with `VaultTransitCipher` calling Vault's `/v1/transit/decrypt/engramia-credentials`. Master key never leaves Vault. |
| **AWS KMS / GCP KMS / Azure Key Vault** | Enterprise | Same pattern as Vault — pluggable cipher backend. Selected via `ENGRAMIA_CREDENTIALS_BACKEND={local,vault,aws_kms,gcp_kms,azure_kv}`. |
| **Per-role model routing** | Business | `role_models` JSONB column populated via `PATCH /v1/credentials/{id}/role-models`. Resolver uses `cred.model_for_role(role)`. |
| **Provider failover chain** | Business | `tenant_credentials` gets `priority` column; resolver tries primary, falls back to secondary on `ProviderError`. |
| **Multi-region key replication** | Enterprise | Vault Transit handles this natively; AWS KMS via multi-region keys. |
| **Bring-your-own-master-key (BYOMK)** | Enterprise | Tenant supplies their own master key via Vault namespace; Engramia decrypts via tenant's Vault, not operator's. |
| **Provider quota / cost surfacing** | Pro+ | Optional: scrape provider's billing API (OpenAI Usage, Anthropic Console) and surface in dashboard. Tenant grants Engramia read-only access to their billing API. |

---

## 15. Implementation effort summary

Per [Phase 6.6 in roadmap.md](../../../Ops/internal/roadmap.md):

| Component | Effort |
|---|---|
| `engramia/credentials/` package (5 modules) | 4 d |
| Alembic migration `023_tenant_credentials` | 1 d |
| `providers/{gemini,ollama,demo}.py` | 2.5 d |
| Refactor `_factory.py` to per-tenant cache | 2 d |
| API endpoints `/v1/credentials/*` | 2 d |
| Dashboard UI `/settings/llm-providers` | 3 d |
| Onboarding "Skip for now" + demo banner | 1 d |
| Documentation (this file + provider setup guides) | 2 d |
| Stripe pricing migration to 5-tier | 0.5 d |

**Total BYOK foundation: ~14 days** of focused work. Tier-gated features (Hosted MCP, per-role routing, cross-agent memory, Vault backend, etc.) follow per the [pricing tier roadmap](../../../Ops/internal/PRICING_TIERS_260428.md).

---

## See also

- [Security Architecture](security-architecture.md) — overall trust model, RBAC, multi-tenancy
- [Production Hardening](../production-hardening.md) — TLS, secret management, rate limiting
- [Environment Variables](../environment-variables.md) — `ENGRAMIA_BYOK_ENABLED`, `ENGRAMIA_CREDENTIALS_KEY`, `ENGRAMIA_CREDENTIALS_BACKEND`
- [Pricing](../pricing.md) — tier feature matrix, BYOK availability per tier
