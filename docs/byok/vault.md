# Vault Transit credential backend

> Phase 6.6 #6. Enterprise-tier feature. Self-host capable.

By default Engramia stores tenant LLM credentials encrypted at rest with
AES-256-GCM, with the master key in the `ENGRAMIA_CREDENTIALS_KEY`
environment variable. For Enterprise deployments — banks, healthcare,
regulated finance — auditors typically require that the master key live
in a separate trust domain so process compromise does not equal
credential compromise. Engramia supports this via a HashiCorp Vault
Transit backend.

## What changes when you switch

| Aspect | Local backend (default) | Vault Transit backend |
|---|---|---|
| Master key location | Engramia process env var | Inside Vault server, never exported |
| Decrypt audit trail | Engramia application log only | Vault audit log (every decrypt logged with role_id + timestamp + context) |
| Master-key rotation | Master-key bump + DB sweep | Single `vault write -f transit/keys/engramia/rotate` |
| Process-compromise blast radius | All credentials decryptable from DB dump + env | None — DB ciphertext is opaque without Vault |
| Performance | In-process, sub-microsecond | One HTTPS round-trip per cache miss (~5-50 ms) |
| Required dependency | None | `engramia[vault]` (adds `hvac`) plus a reachable Vault cluster |

The credentials API surface (`/v1/credentials/*`), the dashboard
behaviour, and the per-tenant scoping are identical — the swap is
invisible to your tenants.

## When to choose Vault

Pick Vault when **at least one** of the following applies:

- Compliance auditor explicitly asks for KMS-class master-key separation
  (SOC 2, HIPAA, PCI-DSS, ISO 27001 with Annex A.10).
- You already operate Vault for other secrets and want a single audit
  trail.
- You need fine-grained "who decrypted what when" without parsing
  Engramia's own logs (Vault audit backend gives you that natively).
- You want master-key rotation to be a one-line operator action with no
  application redeploy.

If none of those apply, stay on the local backend — it's the default for
a reason and self-hosters under BSL can run Engramia from source without
ever touching Vault.

## Operator setup (one-time)

Setup happens entirely on the Vault side; Engramia just consumes what
Vault produces. The runbook below assumes Vault ≥ 1.13 (Transit derived
key support is older but `derived: true` semantics stabilised in 1.13).

### 1. Mount the Transit secrets engine

```bash
vault secrets enable transit
```

Or, if you prefer a custom mount path (some operators isolate per
application), enable at e.g. `transit-engramia/` and set
`ENGRAMIA_VAULT_TRANSIT_PATH=transit-engramia`.

### 2. Create the encryption key

`derived: true` is **mandatory** — it makes the per-row context
participate in the key derivation, mirroring the AES-GCM AAD defence the
local backend uses.

```bash
vault write -f transit/keys/engramia \
  type=aes256-gcm96 \
  derived=true
```

To override the key name set `ENGRAMIA_VAULT_TRANSIT_KEY=<name>`.

### 3. Create a Vault policy

```hcl
# engramia-decrypt.hcl
path "transit/encrypt/engramia" {
  capabilities = ["update"]
}

path "transit/decrypt/engramia" {
  capabilities = ["update"]
}
```

```bash
vault policy write engramia-decrypt engramia-decrypt.hcl
```

The policy gives Engramia exactly two operations and nothing else — no
key rotation, no key export, no list. Operators retain full control of
the master key.

### 4. Enable AppRole auth and create a role

```bash
vault auth enable approle

vault write auth/approle/role/engramia \
  token_policies="engramia-decrypt" \
  token_ttl=1h \
  token_max_ttl=8h \
  secret_id_ttl=0 \
  secret_id_num_uses=0
```

`token_ttl=1h` and `token_max_ttl=8h` give Engramia plenty of time to
renew tokens (it does so at half-TTL) without keeping a single token
alive longer than necessary.

### 5. Capture the role_id and a secret_id

```bash
vault read -format=json auth/approle/role/engramia/role-id
# → role_id

vault write -format=json -f auth/approle/role/engramia/secret-id
# → secret_id
```

Both go into Engramia's environment. Treat the `secret_id` like an
ordinary secret — store it in your SOPS-encrypted `.env.prod.enc` (or
the equivalent for your deployment).

### 6. Configure Engramia

Set these on the Engramia process:

```bash
ENGRAMIA_BYOK_ENABLED=true
ENGRAMIA_CREDENTIALS_BACKEND=vault
ENGRAMIA_VAULT_ADDR=https://vault.example.internal:8200
ENGRAMIA_VAULT_ROLE_ID=<role_id>
ENGRAMIA_VAULT_SECRET_ID=<secret_id>
# Optional but recommended:
ENGRAMIA_VAULT_NAMESPACE=engramia        # Vault Enterprise namespaces
ENGRAMIA_VAULT_CA_CERT=/etc/ssl/vault-ca.pem  # if Vault uses a private CA
```

Install the optional dep:

```bash
pip install 'engramia[vault]'
```

Restart. On startup Engramia performs an AppRole login; if it fails the
process exits with a clear error rather than silently falling through.

### 7. Verify

```bash
curl -s https://api.engramia.dev/v1/health/deep | jq '.checks.vault'
# → "ok"
```

The `vault` sub-check probes Vault's `/sys/health` via the cached
client. If it returns anything other than `ok`, follow the troubleshoot
matrix at the bottom of this page before sending traffic.

## Migrating existing credentials

Operators who already have credentials on the local backend migrate via:

```bash
# Dry run first — shows what would change without writing.
engramia credentials migrate-to-vault --dry-run

# Real run — small batches with checkpoint output.
engramia credentials migrate-to-vault --batch-size 100
```

Both backends must be configured during migration: the script reads
local rows (using `ENGRAMIA_CREDENTIALS_KEY`), re-encrypts via Vault,
and writes the new ciphertext back with `backend = 'vault'`. Until the
migration completes, the resolver's per-row dispatch handles a hybrid
state — newly-vaulted rows decrypt via Vault, untouched rows still
decrypt via local. There is no "half-decrypted" window.

If the script crashes mid-way (e.g. Vault outage), resume with:

```bash
engramia credentials migrate-to-vault --continue-from <last_logged_row_id>
```

A maintenance window is recommended but not strictly required — the
migration is online. Plan ~10-50 ms per row depending on Vault latency;
1000 rows ≈ 30-60 seconds.

To roll back (vault → local):

```bash
engramia credentials migrate-to-vault --reverse
```

## What happens when Vault is down

Engramia **fails closed**: any operation that needs to decrypt a Vault
row returns `503 Service Unavailable` to the caller. The cache is not
consulted as a fallback, by design (compliance auditors require that a
revoked credential cannot remain usable through a stale cache during a
Vault outage).

Recovery is automatic — once Vault returns, the next request decrypts
normally. There is no admin action required.

Watch the `engramia_vault_unreachable_total` Prometheus counter and the
`VAULT_UNREACHABLE` log line for outage alerts.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `BYOK enabled but credential backend init failed: AppRole login to Vault at https://... failed: 403` | Wrong role_id or secret_id, or the secret_id has expired | Regenerate secret_id with `vault write -f auth/approle/role/engramia/secret-id`; redeploy with new env value |
| `503` on every credential operation, log says `VAULT_UNREACHABLE` | Vault is sealed, network partition, or DNS flap | Check Vault status (`vault status`); re-key/unseal if needed |
| `503` only on a specific row, log says `CREDENTIAL_DECRYPT_FAILURE` | Vault decrypt rejected the context — typically means the row was created against a different Transit key (or a row migration was incomplete) | Re-run `engramia credentials migrate-to-vault --tenant <id>` for that tenant |
| New tenant credentials get encrypted but immediate decrypt fails | Transit key was created with `derived=false` | Recreate the key with `derived=true`; existing rows must be re-encrypted |
| Health probe says `vault: auth_failed` after working for hours | `token_max_ttl` reached, AppRole re-login also failed | Inspect Vault audit log for the failing login; usually a stale secret_id |

## Reference

- Architecture: `Ops/internal/vault-credential-backend-architecture.md`
  (private; design rationale, ADRs, sequence diagrams)
- Operator runbook with real hostnames: `Ops/runbooks/vault-credentials-setup.md`
  (private)
- Vault Transit docs: <https://developer.hashicorp.com/vault/docs/secrets/transit>
- Vault AppRole auth: <https://developer.hashicorp.com/vault/docs/auth/approle>
