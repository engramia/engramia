# Engramia Pre-Launch Audit — 2026-04-05

**Rozsah:** Kompletní code review, docs review, infra review projektu `agent-brain` (v0.6.5).
**Přístup:** Senior Engineer + Product Manager + Project Manager perspektiva.
**Auditovaný commit:** HEAD na main větvi, stav k 2026-04-05.

---

## 1. Sync UAT ↔ User Guide

### 1.1 Pokryto v obou — OK

| UAT sekce (docs/uat.md) | User Guide sekce (docs/user-guide.md) | Verdikt |
|---|---|---|
| 1. Auth & Registration (bootstrap, API keys, RBAC) — 25 testů | Sec. 3 (Installation), Sec. 4 (Auth modes) | OK |
| 2. Core API (learn/recall/evaluate/compose/evolve/skills/feedback/metrics/health/jobs) — 35 testů | Sec. 5 (Core API — How to Use) | OK |
| 3. Billing (status, checkout, portal, overage, dunning) — 28 testů | Sec. 6 (Billing Cloud) | OK |
| 4. GDPR/DSR (retention, export, classification, project/tenant delete) — 22 testů | Sec. 7 (GDPR and Data) | OK |
| 5. Webhooks (Stripe — 9 testů) | Zmíněno v Sec. 6 (grace period), ale ne detailně | Partial |
| 6. Monitoring (Prometheus, audit log, maintenance mode) — 9 testů | Sec. 11 (Monitoring) + Sec. 4 (Observability vars) | OK |
| 7. Security (rate limiting, body size, headers, CORS, cross-tenant, quota) — 18 testů | Sec. 8 (Limits and Rate Limiting) | OK |

Celkem UAT: **146 testovacích kroků** ve 7 sekcích. Pokrytí hlavních API flows je solidní.

### 1.2 V UAT, ale chybí nebo nedostatečně v User Guide

**5. Stripe Webhooks** (UAT 5.1–5.9, 9 testů: trigger, idempotence, bad signature): User Guide nemá žádnou sekci o webhook konfiguraci pro self-hosted deployment. `STRIPE.md` existuje ale je interní CZ dokument, není součástí user-facing docs. Doporučení: přidat Sec. 6.x "Webhook Setup" do `docs/user-guide.md`.

**1.2 Key rotation** (UAT 1.2.10–1.2.12): `POST /v1/keys/{id}/rotate` je zmíněn jen v tabulce Sec. 5.8 — žádný curl ani python příklad. Doporučení: přidat příklad do Sec. 5.8.

**1.2 Key expiration** (UAT 1.2.13–1.2.14): Parametr `expires_at` není nikde v User Guide zdokumentován. Doporučení: přidat do Sec. 4 (Authentication).

**2.5 Evolve + Analyze Failures**: Označeny "Experimental" v nadpisu sekcí 5.5 a 5.6, ale User Guide nemá žádné explicitní upozornění na produkční stabilitu nebo API stability. Doporučení: přidat `> **Experimental — API may change**` callout.

**6.2 Audit Log** (UAT 6.2.1–6.2.5, testuje auth_failure, pattern_deleted, data_exported, bulk_import, formát): User Guide nemá sekci o čtení a interpretaci audit logů. Admin nemá návod jak audit logy najít, filtrovat, nebo interpretovat. Doporučení: přidat novou Sec. 11.x "Audit Log".

**3.6 Dunning** (UAT 3.6.1–3.6.2, grace period logika): User Guide Sec. 6 popisuje grace period flow, ale chybí info jak admin vidí dunning stav. Žádný API endpoint ani dashboard panel pro "vaše platba selhala, zbývá X dní". Doporučení: dokumentovat dunning visibility v Sec. 6.

**4.5–4.6 DSR** (Data Subject Requests): `governance/dsr.py` podporuje DSR tracking s `ENGRAMIA_DSR_SLA_DAYS` env var, ale User Guide nemá DSR workflow dokumentaci. Zákazník neví jak podat DSR request. Doporučení: přidat DSR flow do Sec. 7.

### 1.3 V User Guide, ale chybí v UAT

**Sec. 10 Integrations** (LangChain callback, CrewAI callback, MCP server, EngramiaBridge SDK, Webhook): Žádné UAT testy pro SDK integrace. Impact: medium — SDK je wrapper nad REST API, ale end-to-end test chybí.

**OIDC SSO** (auth mode `oidc` — Sec. 4): UAT testuje jen `db` auth mode, ne OIDC flow. Impact: medium — enterprise zákazníci budou potřebovat OIDC UAT.

**CLI** (`engramia` CLI tool): UAT je čistě API-only. Impact: low — CLI volá REST API interně a je testováno unit testy.

**Python library** (direct `Memory` class usage): UAT pokrývá jen REST API. Impact: low — library je testována unit testy (726+).

### 1.4 Verdikt sekce 1

UAT a User Guide jsou z přibližně 80% synchronizované. Hlavní mezery jsou webhook docs, audit log docs, key rotation/expiration příklady, a DSR workflow. UAT chybí pokrytí OIDC a SDK integrací.

---

## 2. Technická připravenost

### 2.1 .env.example — NEÚPLNÝ

`.env.example` obsahuje 14 proměnných. Kód ale používá 46 unikátních env vars (ověřeno grepem přes `os.environ.get` v celém `engramia/`). Kritické chybějící proměnné:

**BLOCKING — production bez nich nefunguje:**

`ENGRAMIA_AUTH_MODE` (použit v `api/app.py:62`, `api/auth.py:56`) — prod musí explicitně nastavit `db`. Bez toho se použije `auto` které může spadnout do env mode.

`ENGRAMIA_BOOTSTRAP_TOKEN` (použit v `api/keys.py:206`) — bez něj nelze vytvořit první API key. Bootstrap endpoint je chráněn tímto tokenem + `pg_advisory_xact_lock`.

`ENGRAMIA_DATABASE_URL` — je v .env.example ale zakomentován. Prod vyžaduje PostgreSQL. Měl by být aktivní v produkčním template.

`POSTGRES_PASSWORD` (použit v `docker-compose.prod.yml:22`) — PG kontejner neodstartuje bez hesla. Není v .env.example vůbec.

**IMPORTANT — production bude slepý nebo nezabezpečený bez nich:**

`ENGRAMIA_METRICS=true` (`api/app.py:335`) — bez tohoto se `/metrics` endpoint vůbec nezaregistruje.

`ENGRAMIA_METRICS_TOKEN` (`api/app.py:345`) — bez tohoto je `/metrics` bez autentizace (pokud je `ENGRAMIA_METRICS=true`).

`ENGRAMIA_JSON_LOGS=true` (`telemetry/__init__.py:46`) — bez tohoto jsou logy plaintext, ne structured JSON. Loki/Promtail je nenaparsuje.

`ENGRAMIA_ENVIRONMENT=production` (`api/app.py:67`) — guard proti dev mode v produkci.

`ENGRAMIA_REDACTION=true` (`api/app.py:283`) — defaultně true, ale mělo by být explicitně v .env pro viditelnost.

`STRIPE_SECRET_KEY` (`billing/stripe_client.py:31`) — bez tohoto billing běží v no-op mode.

`STRIPE_WEBHOOK_SECRET` (`billing/stripe_client.py:32`) — bez tohoto webhooky nemohou ověřit signature.

`GRAFANA_ADMIN_PASSWORD` (`docker-compose.monitoring.yml`) — default je `changeme`.

**NICE-TO-HAVE (nedůležité pro basic launch):**

`ENGRAMIA_TELEMETRY`, `ENGRAMIA_OTEL_ENDPOINT`, `ENGRAMIA_OTEL_SERVICE_NAME`, `ENGRAMIA_MAINTENANCE`, `ENGRAMIA_JOB_POLL_INTERVAL`, `ENGRAMIA_JOB_MAX_CONCURRENT`, `ENGRAMIA_LLM_TIMEOUT`, `ENGRAMIA_LLM_CONCURRENCY`, `ENGRAMIA_DSR_SLA_DAYS`, `ENGRAMIA_MAX_LLM_RESPONSE`, `ENGRAMIA_SKIP_AUTO_APP`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ENGRAMIA_OIDC_ISSUER`, `ENGRAMIA_OIDC_AUDIENCE`, `ENGRAMIA_OIDC_ROLE_CLAIM`, `ENGRAMIA_OIDC_DEFAULT_ROLE`, `ENGRAMIA_OIDC_TENANT_CLAIM`, `ENGRAMIA_OIDC_PROJECT_CLAIM`, `ENGRAMIA_API_URL`, `ENGRAMIA_API_KEY`, `ENGRAMIA_LOCAL_EMBEDDINGS`, `GIT_COMMIT`, `BUILD_TIME`.

Doporučení: vytvořit dva .env soubory — `.env.example` (dev, stávající) a `.env.production.example` (prod se všemi relevantními vars a komentáři).

### 2.2 DB migrace

Revision chain:
```
None → 001 → 002 → 003 → 004 → 005 → 006 → 008 → 009 → 010 → 011 → 012
```

Chain integrity: OK. Všechny `down_revision` hodnoty jsou korektní. Chain je lineární, žádné branche (`branch_labels = None` všude).

Gap 007: Soubor `007_*.py` neexistuje. `008_billing.py` má `down_revision = "006"` (správně), takže chain je funkční. Ale docstring v `008_billing.py` říká "Revises: 007" — stale komentář, kosmetický problém.

`env.py` (`engramia/db/migrations/env.py`, 64 řádků): Korektní setup. `_get_url()` helper čte `ENGRAMIA_DATABASE_URL` env var, fallback na `sqlalchemy.url` z `alembic.ini`. Online mode používá `pool.NullPool` (správná praxe pro migrace). Offline mode podporován s `literal_binds=True`.

Aplikovatelnost na čistou DB: Nelze ověřit z repo — vyžaduje running PostgreSQL instance. Musí být součástí UAT (UAT předpoklad: "Všechny DB migrace proběhly (`alembic upgrade head`)").

### 2.3 docker-compose.prod.yml

Restart policies: OK — `restart: unless-stopped` na všech třech services (caddy, engramia-api, pgvector).

Healthchecks: OK — API: `curl -f http://localhost:8000/v1/health` (interval 30s, timeout 5s, retries 3). PG: `pg_isready -U engramia` (interval 10s, timeout 5s, retries 5). Caddy nemá explicitní healthcheck ale to je OK — Caddy je self-healing.

Resource limits: **CHYBÍ**. Žádné `mem_limit`, `cpus`, ani `deploy.resources` na API ani PG kontejnerech. Přitom `docker-compose.monitoring.yml` resource limits **má** (`prometheus: 256m`, `grafana: 192m`, `alertmanager: 64m`, `loki: 256m`, `promtail: 64m`, `uptime-kuma: 128m`). Nekonzistence — monitoring je chráněn proti OOM, ale hlavní aplikace ne.

Non-root user: OK — Dockerfile: `USER engramia` (UID/GID 1001), `addgroup --gid 1001 --system engramia && adduser ...`.

Network isolation: OK — dedicated `engramia-net` bridge. API port mapován na `127.0.0.1:8000` (ne `0.0.0.0`) — API není přímo přístupná z internetu, jen přes Caddy.

Named volumes: OK — `pgdata`, `engramia_data`, `caddy_data`, `caddy_config`.

Image pinning: OK — `caddy:2.9.1-alpine`, `pgvector/pgvector:0.7.4-pg16` — konkrétní verze, ne `latest`.

Depends_on: OK — API závisí na PG s `condition: service_healthy`.

### 2.4 Backup strategie

Dokumentace: OK — `docs/backup-restore.md` definuje RTO 4h / RPO 24h. Obsahuje `pg_dump` postup krok za krokem.

Recovery: OK — `docs/runbooks/database-recovery.md` pokrývá full restore, point-in-time recovery.

Automatizovaný backup script: **CHYBÍ**. V repo je `scripts/monitoring.sh` ale žádný `scripts/backup.sh`. Backup je jen zdokumentován, ne implementován. Žádný cron job, žádný Docker sidecar, žádný pg_dump wrapper.

Off-site backup: Nelze zjistit z repo. Docs doporučují off-site, ale implementace není viditelná.

### 2.5 TLS/HTTPS

Caddy reverse proxy: OK — `Caddyfile` má `api.engramia.dev { reverse_proxy engramia-api:8000 }`. Caddy automaticky získá a obnoví Let's Encrypt certifikát pro tento domain.

HSTS: OK — Caddy přidává `Strict-Transport-Security` header automaticky (default behavior, ověřeno v `docs/production-hardening.md` a `docs/security-architecture.md`).

HTTP→HTTPS redirect: OK — Caddy by default redirectuje HTTP na HTTPS.

Internal API binding: OK — `docker-compose.prod.yml` mapuje API port na `127.0.0.1:8000`, takže API je přístupná výhradně přes Caddy reverse proxy.

Chybí explicitní Caddyfile konfigurace pro website domain (`engramia.dev`). Caddyfile má jen `api.engramia.dev`. Pokud website běží na jiném serveru (Netlify/Vercel), je to OK. Pokud má běžet na stejném VM, chybí konfigurace.

### 2.6 Secrets management

`.env` file: OK pro single-VM MVP. Secrets v `.env` souboru — standard pro menší deploymenty.

`.gitignore`: OK — obsahuje `.env`, `*.pem`, `*.key`, `*.crt`, `*.p12`, `credentials*` (opraveno v v0.6.2 po audit finding).

K8s secrets: `deploy/k8s/engramia.yaml` používá `Secret` objekt s `stringData` — plaintext v YAML manifestu. Pro produkční K8s deployment by měl být nahrazen SealedSecrets, SOPS, nebo external secret operator.

External secret management: Naplánováno jako budoucí Enterprise feature (`roadmap.md:188` — HashiCorp Vault / AWS Secrets Manager / Azure Key Vault).

### 2.7 Verdikt sekce 2

Infrastruktura je solidní pro single-VM MVP launch. Docker compose je production-ready kromě chybějících resource limits. TLS je správně přes Caddy. Hlavní gaps: neúplný .env.example (28 chybějících vars z produkčně relevantních), chybějící backup automatizace, a žádný external secret management (acceptable pro MVP).

---

## 3. CI/CD Pipeline

### 3.1 Existující workflows

**CI** (`.github/workflows/ci.yml`): Trigger na push/PR to main. Dva joby:
- `test`: ruff check, ruff format --check, mypy (continue-on-error: true), pytest --cov=engramia --cov-report=xml --cov-fail-under=80, codecov upload. Python 3.12 matrix.
- `version-consistency`: hatchling version smoke, no hardcoded `__version__` check, pyproject.toml dynamic version check. Requires fetch-depth: 0 pro hatch-vcs.

**Docker** (`.github/workflows/docker.yml`): Trigger na GitHub Release published. Multi-arch Docker build s build-args (`GIT_COMMIT`, `BUILD_TIME`, `APP_VERSION`), push to GHCR (`ghcr.io/engramia/engramia`). Post-deploy smoke test ověřuje `/v1/health` a `/v1/version` version parity (tag == runtime version).

**Publish** (`.github/workflows/publish.yml`): Trigger na GitHub Release published. Build s hatch-vcs, publish to PyPI.

**Dependabot** (`.github/dependabot.yml`): Automatické weekly dependency update PRs.

### 3.2 Co funguje dobře

Version consistency pipeline je dobře navržen — hatch-vcs odvozuje verzi z git tagů, CI ověřuje konzistenci, Docker build injectuje verzi jako build-arg, a post-deploy smoke test ověřuje že runtime verze odpovídá release tagu. End-to-end version integrity.

Coverage threshold na 80% (aktuálně 80.29%) je rozumný a enforcement v CI funguje.

Dependabot automaticky detekuje dependency updates.

### 3.3 Problémy

**mypy je continue-on-error: true** (ci.yml, test job, mypy step): Type checking failures neblokují merge. To znamená že type errors se mohou akumulovat bez povšimnutí. Buď přejít na strict (remove continue-on-error) nebo step zcela odstranit pokud není plán ho opravit.

**Žádné integration testy v CI**: 30 PostgreSQL integration testů v `tests/postgres/` (test_integration_postgres.py, test_postgres_storage.py, test_postgres_storage_unit.py) se nespouští v CI. Vyžadují `testcontainers` a Docker-in-Docker nebo PG service container. CI testuje jen JSON storage path.

**Žádný security scan**: Chybí SAST (bandit, semgrep), dependency vulnerability scan (pip-audit, safety, Snyk), a secret scanning. Pro SaaS produkt zpracovávající zákaznická data je to significant gap.

**PyPI environment protection**: `roadmap.md:162` explicitně říká "PyPI environment protection → release trigger in publish.yml" jako TODO. Bez toho kdokoli s write access k repo může vytvořit GitHub Release a triggerovat publish to PyPI. BLOCKING.

**Žádný staging deploy workflow**: Pouze release-triggered deploy. Žádný preview/staging pro PRs. Nice-to-have pro velocity.

**Coverage regression neblokuje**: Codecov upload existuje s `fail_ci_if_error: false`. Codecov může zachytit regressions ale pokud Codecov service spadne, CI projde.

### 3.4 Verdikt sekce 3

CI/CD pipeline existuje a pokrývá základy (lint, test, build, publish, version consistency). Hlavní problémy: PyPI environment protection je blocking TODO, chybí security scanning, a PG integration testy se nespouští v CI.

---

## 4. Security Pre-Launch Checklist

### 4.1 OWASP Top 10 Quick Scan

**A01 Broken Access Control**: OK. RBAC se 4 rolemi (owner > admin > editor > reader) v `api/permissions.py`. Scope isolation via contextvars (`_context.py`) + DB queries scoped na `(tenant_id, project_id)`. `UNIQUE(tenant_id, project_id, key)` constraint (migration 009). Cross-tenant testy v `tests/test_security/test_tenant_isolation.py`. Role hierarchy enforced v `keys.py` — owner může vystavit libovolnou roli, admin maximálně editor, editor a reader nemohou vystavovat klíče. Cross-project delete fix: non-owner role může smazat jen vlastní projekt (v0.6.5).

**A02 Cryptographic Failures**: OK. TLS via Caddy auto-TLS (Let's Encrypt). Timing-safe auth comparison (`hmac.compare_digest` v `auth.py`). API keys hashovány před uložením do DB. Žádné plaintext secrets v API responses — klíč se zobrazí jen jednou při vytvoření.

**A03 Injection**: OK. SQLAlchemy 2.x ORM s parameterized queries v `providers/postgres.py` a `db/models.py`. LIKE wildcard escaping implementován. Prompt injection mitigation: `<recurring_issues>` delimiter wrapper v `PromptEvolver` (v0.6.5). UAT test 7.5.2 explicitně testuje SQL injection v query parametrech.

**A04 Insecure Design**: OK. Defense-in-depth vrstvení: auth middleware → RBAC check → scope isolation → rate limiting → body size limit → PII redaction → audit logging. Billing quota enforcement jako další vrstva (eval_runs + patterns limits).

**A05 Security Misconfiguration**: Partial. `ALLOW_NO_AUTH` truthy string parsing opraveno ve v0.6.5 (dříve `"false"` bylo truthy). `ENGRAMIA_ENVIRONMENT` guard blokuje dev mode v non-local prostředích. Ale guard závisí na správné konfiguraci env var — pokud admin nenastaví `ENGRAMIA_ENVIRONMENT=production`, guard nefunguje. Ne fail-safe.

**A06 Vulnerable Components**: GAP. Dependabot existuje pro automatické PRs, ale žádný CI step aktivně skenuje dependencies na known vulnerabilities. Nelze ověřit aktuální stav bez `pip audit` run. Doporučení: přidat `pip-audit` nebo `safety` do CI.

**A07 Authentication Failures**: OK. Bootstrap endpoint chráněn s `ENGRAMIA_BOOTSTRAP_TOKEN` (min 32 chars) + `pg_advisory_xact_lock` pro atomicitu (v0.6.5). Key rotation, revocation, expiration implementovány. 60s TTL cache s okamžitou invalidací při revokaci. Audit logging pro všechny auth failures (event `auth_failure` s `ip`, `reason`).

**A08 Software and Data Integrity**: OK. Stripe webhook HMAC-SHA256 verification (`stripe.Webhook.construct_event()`). Idempotent event processing přes `processed_webhook_events` tabulku (migration 011). Alembic migration chain integrity ověřena (lineární, žádné branches). Docker images s OCI labels (version, revision, created).

**A09 Security Logging and Monitoring Failures**: OK. Structured JSON logging (`telemetry/logging.py`) s context injection (request_id, trace_id, span_id, tenant_id, project_id). Audit log (`api/audit.py`) pro security events. OTel tracing support. Prometheus `/metrics` s autentizací (`ENGRAMIA_METRICS_TOKEN`). Alert rules v `monitoring/alerts.rules.yml`.

**A10 Server-Side Request Forgery**: N/A. API nevytváří outbound HTTP požadavky na user-supplied URLs. LLM calls jdou na fixed provider URLs (OpenAI API, Anthropic API). Webhook URL pro Stripe je konfigurován přes Stripe Dashboard, ne přes API.

### 4.2 Detailní security checklist

| Check | Status | Evidence |
|---|---|---|
| SQL injection ochrana | OK | SQLAlchemy ORM, parameterized queries, `providers/postgres.py` |
| Všechny endpointy vyžadují auth | OK | Výjimky: `/v1/health`, `/v1/version`, `/v1/billing/webhook` (Stripe signature místo Bearer), `/metrics` (vlastní token). Všechny záměrné a zdokumentované. |
| Sensitive data v logách | OK | `RedactionPipeline` defaultně zapnuta (`api/app.py:283`, `ENGRAMIA_REDACTION=true`). Job tracebacks sanitized — API vrací jen `ExcType: message`, plný traceback jen v server logs (v0.6.5). |
| HTTPS enforced | OK | Caddy auto-TLS, API na `127.0.0.1` only |
| Rate limiting — standard endpoints | OK | 60 req/min per IP per path (`middleware.py:16`) |
| Rate limiting — LLM endpoints | OK | 10 req/min per IP per path pro `/v1/evaluate`, `/v1/compose`, `/v1/evolve` (`middleware.py:17`) |
| Rate limiting — per API key | OK | 120 req/min total across all paths (`middleware.py:18`) |
| Security headers | OK | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `X-Permitted-Cross-Domain-Policies: none` (`middleware.py:61-68`) |
| CORS | OK | Disabled by default. Opt-in via `ENGRAMIA_CORS_ORIGINS` env var. |
| Body size limit | OK | 1MB default, configurable via `ENGRAMIA_MAX_BODY_SIZE` (`middleware.py:23`) |
| OIDC algorithm allowlist | OK | RS256, RS384, RS512, ES256, ES384, ES512, PS256, PS384, PS512. `"none"` a HMAC (HS*) odmítnuty (`api/oidc.py`, v0.6.5). |
| `/metrics` authentication | OK | `ENGRAMIA_METRICS_TOKEN` Bearer guard. Bez tokenu: 401/403. (`api/app.py:345`, v0.6.5) |
| Cross-tenant isolation | OK | Scope contextvars + `UNIQUE(tenant_id, project_id, key)` constraint (migration 009). Testy v `test_security/test_tenant_isolation.py`. |
| Prompt injection mitigation | OK | `<recurring_issues>` XML delimiter wrapper v `PromptEvolver` (v0.6.5) |
| Timing attack resistance | OK | `hmac.compare_digest` pro key comparison. UAT 7.5.3 testuje timing attack. |
| Error sanitization | OK | Tracebacks jen server-side. API vrací generické chybové zprávy. |

### 4.3 Známé omezení (akceptovatelná pro MVP)

**In-memory rate limiter**: `RateLimitMiddleware` je single-process, in-memory dictionary s thread lock. Při škálování na >1 repliku se rate limiting obejde (každá replika má vlastní counter). `docs/production-hardening.md` toto explicitně zmiňuje a doporučuje Redis-backed limiter pro scale-out. Riziko: low pro launch na single VM.

**Žádný WAF**: Caddy nemá WAF plugin. Aplikace spoléhá na vlastní middleware (body size, rate limit, security headers). Riziko: low — přijatelné pro MVP. Caddy komunita nemá mainstream WAF plugin.

**60s TTL key cache**: Revokovaný API klíč může fungovat až 60 sekund po revokaci (in-memory cache v `auth.py`). Riziko: low — dokumentováno, 60s okno je přijatelné pro B2B SaaS.

### 4.4 Historické audit findings — všechny resolved

Audit 2026-03-28 (score 78/100): 15 findings (P0–P3). Všechny resolved ve v0.5.3–v0.6.0. Klíčové: tenant isolation, RBAC, quota enforcement, async jobs, telemetry, data governance, admin UI, test coverage.

Audit 2026-04-02 (score 83/100): 10 findings (P1–P2). Všechny resolved ve v0.6.2–v0.6.3. Klíčové: auth fallback, cross-tenant feedback leak, analytics race condition, job durability, embedding metadata, RBAC in env mode.

Audit 2026-04-04: 10 findings (P0–P2). Všechny resolved ve v0.6.5. Klíčové: role escalation, bootstrap takeover, cross-project delete, traceback leak, ALLOW_NO_AUTH parsing, redaction wiring, /metrics auth, scope-aware DB identity, OIDC algorithm allowlist, prompt evolver delimiter.

### 4.5 Verdikt sekce 4

Security je na velmi dobré úrovni. Tři audit cykly proběhly a všechny P0–P2 nálezy jsou resolved. OWASP Top 10 pokrytí je kompletní kromě A06 (vulnerable components — chybí automated scanning v CI). Pro B2B SaaS s financial data (billing) je to solid foundation.

---

## 5. Product/UX Mezery

### 5.1 Onboarding flow

**Self-hosted onboarding**: OK. User Guide Sec. 3 poskytuje jasný 5-krokový postup: (1) clone repo, (2) vytvořit .env, (3) docker compose up, (4) alembic upgrade head, (5) bootstrap API key. Pak Sec. 2 dává learn/recall/health smoke test příklady.

**Cloud onboarding**: BLOCKING GAP. User Guide Sec. 2 "Quick Start (Cloud)" říká:
1. "Go to `https://api.engramia.dev/docs` — this opens the Swagger UI."
2. "The Sandbox tier is free, no credit card required."

Ale: (a) kde se uživatel zaregistruje? Žádná signup page neexistuje. (b) Kdo provede bootstrap? Bootstrap vyžaduje `ENGRAMIA_BOOTSTRAP_TOKEN` — to je server-side secret. (c) Jak zákazník získá API key bez přístupu k serveru? (d) Website pricing CTA pro Sandbox říká "Try free → https://api.engramia.dev/docs" — to jen otevře Swagger, ne signup.

Flow od nového cloud zákazníka po první API call není definován. Tohle je fundamentální product gap.

**First-value-time**: Partial. Learn → Recall demo je v Sec. 2, ale chybí guided příklad pro reálný use case. Něco jako "Integrate with your LangChain agent in 5 minutes" by výrazně zkrátil time-to-value.

### 5.2 Error messages

Strukturované chyby: OK. JSON responses s `detail`, `error`, `metric`, `current`, `limit`, `reset_date` fieldy. Příklad quota error: `{"error": "quota_exceeded", "metric": "eval_runs", "current": 500, "limit": 500, "reset_date": "2026-05-01"}`.

User-friendly: OK. HTTP 429 vysvětluje co je přečerpáno a kdy se resetuje. HTTP 402 říká "update payment method". HTTP 503 v maintenance mode říká "Service is under scheduled maintenance" s `Retry-After: 3600` header.

Troubleshooting guide: OK. User Guide Sec. 9 pokrývá HTTP 401, 402, 429, 413, 501, 503 s příčinami a řešeními.

### 5.3 API dokumentace

Swagger UI (`/docs`): OK — FastAPI auto-generates z Pydantic modelů (`api/schemas.py`).
ReDoc (`/redoc`): OK — alternativní view.
`docs/api-reference.md`: OK — MkDocs-hosted reference.
`docs/rest-api.md`: OK — endpoint listing s příklady.
`docs/api-stability.md`: OK — definuje API versioning policy.

### 5.4 Changelog

OK — `CHANGELOG.md` existuje a je aktuální. Pokrývá všechny fáze od v0.1.0 po v0.6.5 s detailními release notes.

### 5.5 Status page

Uptime Kuma: deployed v `docker-compose.monitoring.yml` na portu `127.0.0.1:3001`.

Public-facing URL: CHYBÍ. Uptime Kuma je jen na localhost, nepřístupná pro zákazníky. Žádný `status.engramia.dev` subdomain nakonfigurován v Caddyfile. Zákazníci nemají kam se podívat při výpadku.

### 5.6 Verdikt sekce 5

API dokumentace a error handling jsou solidní. Hlavní gap: cloud onboarding flow není definován (blocking). Status page není public (important).

---

## 6. Business Readiness

### 6.1 Legal dokumenty

**Terms of Service**: Existuje v `docs/legal/TERMS_OF_SERVICE.md` a na website (`/legal/terms-of-service/`). BLOCKING: `roadmap.md:148` — "Czech attorney review: ToS (B2C/GDPR)" je TODO.

**Privacy Policy**: Existuje v `docs/legal/PRIVACY_POLICY.md` a na website. BLOCKING: `roadmap.md:151` — "Privacy Policy: add encryption at rest (§7), anonymization (§4.3)" je TODO.

**Cookie Policy**: Existuje v `docs/legal/COOKIE_POLICY.md` a na website. Needs attorney review.

**DPA (Data Processing Agreement)**: Existuje v `docs/legal/DPA_TEMPLATE.md` a na website. BLOCKING: `roadmap.md:152` — "DPA: add sub-processor list (§4.4) + public `/legal/subprocessors` page" je TODO.

**Commercial License Template**: Existuje v `docs/legal/COMMERCIAL_LICENSE_TEMPLATE.md` a na website. OK.

**SECURITY.md**: Existuje v root. Definuje responsible disclosure na `security@engramia.dev`. OK.

**LICENSE.txt**: BSL 1.1. IMPORTANT: `roadmap.md:147` — "LICENSE.txt structural fix — reorder per BSL 1.1 boilerplate (mariadb.com/bsl11)" je TODO.

**Dependency licenses**: `docs/legal/dependency-licenses.md` + JSON. 103 Python packages + 13 frontend packages, 0 license blockers. OK.

**Key legal design decisions**: `docs/legal/key-legal-design-decisions.md` — dokumentuje rationale za BSL 1.1, CLA policy, DPA approach. OK.

**Pricing URL placeholders**: `roadmap.md:150` — "Fill placeholders — pricing URL in ToS/Privacy/Cookie/DPA" je TODO. Legal dokumenty mají placeholder URLs místo skutečných.

### 6.2 Support kanály

`sales@engramia.dev`: Zmíněn v website footer, pricing CTA pro Enterprise, STRIPE.md.

`legal@engramia.dev`: Zmíněn v website footer.

`security@engramia.dev`: Zmíněn v `SECURITY.md` pro responsible disclosure.

Technický support: CHYBÍ. Žádný `support@engramia.dev`, Discord server, Slack community, Intercom, ani Zendesk. Pro paying customers (Pro $29/mo, Team $99/mo) není definován support channel kromě GitHub Issues.

Email monitoring: BLOCKING. `roadmap.md:154` — "Verify all project email addresses exist and are monitored: `security@engramia.dev`, `legal@engramia.dev`, `sales@engramia.dev`" je TODO. Emaily mohou neexistovat.

### 6.3 Feedback mechanismus

GitHub Issues: OK. Bug report template existuje v `.github/ISSUE_TEMPLATE/bug_report.yml`.

Feature request template: CHYBÍ. Jen bug report, žádný feature request template.

In-app feedback / NPS: CHYBÍ.

### 6.4 Website / SEO

**Landing page** (`website/website/src/app/page.tsx`): OK. Hero section s badge "Reusable execution memory for AI agents", headline "Make agent systems learn from what already worked", dvě CTA ("Start with Pro", "Explore API docs"), tři feature karty (Learn, Recall, Improve), features section, pricing preview.

**Pricing page** (`website/website/src/app/pricing/page.tsx`): OK. 6 tierů v gridu — 4 cloud (Sandbox, Pro, Team, Enterprise Cloud) + 2 self-hosted (Developer License, Enterprise Self-hosted). CTAs linkují na checkout/docs/mailto.

**Licensing page** (`website/website/src/app/licensing/page.tsx`): OK. Interaktivní "Can I use this for X?" matrix s 11 use cases, color-coded verdicts, 5 FAQs.

**Blog** (`website/website/src/app/blog/`): OK. 3 launch blog posty připraveny — "Why agent memory breaks in production" (Engineering), "Pricing agent infrastructure without killing adoption" (Business), "What evaluation insights should actually show" (Product). Dynamic routing `/blog/[slug]`.

**Legal pages** (`website/website/src/app/legal/`): OK. 6 markdown docs, dynamic routing `/legal/[slug]`, centrální hub page.

**robots.txt**: CHYBÍ. `website/website/public/` obsahuje jen `favicon.svg`. Žádný robots.txt.

**sitemap.xml**: CHYBÍ. Žádná konfigurace pro sitemap generaci. Žádný `next-sitemap` package.

**Open Graph / Twitter cards**: CHYBÍ. `website/website/src/app/layout.tsx` má jen basic `title: "Engramia"` a `description: "Reusable execution memory for AI agents."`. Žádné `og:image`, `og:title`, `og:description`, `twitter:card`, `twitter:image`. Sdílení na sociálních sítích bude vypadat prázdně.

**Custom 404 page**: Partial. Žádný `not-found.tsx` v root. Dynamic routes používají `notFound()`. Default Next.js 404 — ne branded.

**Favicon**: OK — `favicon.svg`.

### 6.5 Launch plán

Blog post drafty: OK — 3 posty v `website/src/content/blog.ts`.

Product Hunt draft: Nelze zjistit z repo.

HN post draft: Nelze zjistit z repo.

Launch timeline: Nelze zjistit z repo. `roadmap.md` má TODO items ale žádné konkrétní datumy.

EUIPO trademark registration: `roadmap.md:149` — TODO. Status neznámý.

### 6.6 Verdikt sekce 6

Legal dokumenty existují ale potřebují attorney review — to je hlavní business blocker. Website je obsahově připravená ale chybí SEO basics (robots.txt, sitemap, OG tags). Email monitoring je neověřen. Technický support kanál chybí.

---

## 7. Operační Readiness

### 7.1 Runbooks

Vynikající pokrytí — 12 runbooks v `docs/runbooks/`:

| Runbook | Soubor | Obsah |
|---|---|---|
| Incident response | `docs/runbooks/incident-response.md` | Severity levels (P1–P4), escalation paths, post-mortem template |
| Database recovery | `docs/runbooks/database-recovery.md` | pg_dump/restore, point-in-time recovery, validation steps |
| Deploy & rollback | `docs/runbooks/deploy-rollback.md` | Docker rollback via IMAGE_TAG, K8s rollout undo, Alembic downgrade |
| LLM provider outage | `docs/runbooks/llm-provider-outage.md` | Graceful degradation, fallback behavior, monitoring |
| High error rates | `docs/runbooks/high-error-rates.md` | Diagnosis steps, common causes, remediation |
| High latency | `docs/runbooks/high-latency.md` | PG slow queries, LLM timeouts, connection pool exhaustion |
| Disk full | `docs/runbooks/disk-full.md` | pgdata, Docker logs, /data volume cleanup |
| Job queue issues | `docs/runbooks/job-queue-issues.md` | Stuck jobs, orphan recovery, worker restart |
| API key rotation | `docs/runbooks/api-key-rotation.md` | Key rotation procedure, customer communication |
| Certificate renewal | `docs/runbooks/certificate-renewal.md` | Caddy auto-renewal verification, manual renewal |
| Rate limit tuning | `docs/runbooks/rate-limit-tuning.md` | Config changes, impact assessment |
| Maintenance mode | `docs/runbooks/maintenance-mode.md` | `ENGRAMIA_MAINTENANCE=true` activation/deactivation flow |

### 7.2 Disaster recovery

Backup documentation: OK. `docs/backup-restore.md` definuje RTO 4h, RPO 24h.

Recovery procedure: OK. `docs/runbooks/database-recovery.md` pokrývá full restore, point-in-time recovery.

Automated backup: CHYBÍ. Žádný script ani cron konfigurace v repo. Dokumentace říká "set up cron" ale neposkytuje implementaci.

Off-site backup: Nelze zjistit z repo.

### 7.3 Rollback procedure

Docker rollback: OK. `IMAGE_TAG=v0.6.4 docker compose -f docker-compose.prod.yml up -d`.

K8s rollback: OK. `kubectl rollout undo deployment/engramia-api -n engramia`.

Alembic downgrade: OK. `alembic downgrade -1` dokumentován.

Rollback testován: Nelze zjistit. Žádný automatizovaný rollback test v CI.

### 7.4 Monitoring stack

Technické metriky: OK. Prometheus + Grafana dashboard (`engramia-overview.json`) s metrikami `engramia_pattern_count`, `engramia_avg_eval_score`, `engramia_total_runs`, `engramia_success_rate`, `engramia_reuse_rate`.

Alert rules: OK. `monitoring/alerts.rules.yml` — high error rate, high latency, disk usage.

Log aggregation: OK. Loki + Promtail.

Uptime monitoring: OK. Uptime Kuma (ale jen internal).

### 7.5 Business metriky — MEZERY

**MRR (Monthly Recurring Revenue)**: CHYBÍ. Žádný Stripe → Grafana pipeline.

**Churn rate**: CHYBÍ. Webhook zpracovává `customer.subscription.deleted`, ale žádný tracking over time.

**Active tenants**: CHYBÍ. Žádná DAU/MAU metrika.

**Stripe payment failure alerting**: CHYBÍ. `invoice.payment_failed` webhook nastaví `past_due_since`, ale neposílá alert do ops kanálu.

**Revenue per tier breakdown**: CHYBÍ.

### 7.6 Verdikt sekce 7

Operační readiness je nadprůměrná — 12 runbooks, Prometheus/Grafana/Loki/Alertmanager stack, Uptime Kuma. Hlavní mezery: chybí automatizovaný backup (implementace, ne jen docs), business metriky dashboard, a Stripe failure alerting.

---

## Souhrnné hodnocení

### Co je OK / Připraveno

- **Core API**: 14+ REST endpointů, plně funkční, pokryto 146 UAT testovacími kroky
- **Auth a RBAC**: 5 auth modes, 4 role s hierarchií, kompletní key lifecycle, bootstrap s `pg_advisory_xact_lock`
- **Billing**: Stripe integration s checkout, customer portal, overage billing, dunning, idempotent webhook processing, 4 plan tiers
- **GDPR**: Retention policies, NDJSON streaming export, classification, scoped project/tenant delete, PII redaction pipeline, DSR tracking
- **Security**: 3 kompletní audit cykly, všechny P0–P2 findings resolved (v0.6.2–v0.6.5), OWASP Top 10 pokrytí
- **Testing**: 726+ testů, 80.29% coverage, benchmark suite (254 tasks, 98.8% success rate)
- **Observability**: Prometheus + Grafana + Loki + Promtail + Alertmanager + Uptime Kuma + OTel + structured JSON logging + audit logging
- **Documentation**: User guide (11 sekcí), deployment, production hardening, security architecture, 12 runbooks, SOC 2 mapping
- **Website**: Landing, pricing, licensing, blog (3 posty), legal pages (6 docs)
- **CI/CD**: Lint + test + Docker build/push + PyPI publish + version consistency + dependabot
- **Docker**: Production-ready multi-stage build, non-root, healthchecks, Caddy auto-TLS, pinned images

### Co je nejasné — vyžaduje odpověď od majitele projektu

- **Q1**: Cloud onboarding — jak se nový zákazník zaregistruje a získá API key?
- **Q2**: Email adresy — existují mailboxy `security@`, `legal@`, `sales@engramia.dev` reálně?
- **Q3**: Stripe live mode — je účet připraven (verified business, Tax registration, live products)?
- **Q4**: DNS — je `engramia.dev` a `api.engramia.dev` nakonfigurováno?
- **Q5**: IP ownership — proběhla konzultace s pracovním právníkem?
- **Q6**: EUIPO trademark — podána registrace?
- **Q7**: Živnostenské oprávnění — platné pro SaaS fakturaci?
- **Q8**: GitHub branch protection — nastaveny required reviews a status checks?
- **Q9**: Backup — běží automatizovaný pg_dump cron na VM?
- **Q10**: Launch timing — existuje timeline/datum?

---

## Pre-Launch Checklist

### BLOCKING — musí být hotovo před public release

| # | Položka | Lokace v repo | Owner |
|---|---|---|---|
| B1 | Vytvořit `.env.production.example` se všemi produkčně relevantními vars | `.env.example` | Engineering |
| B2 | Czech attorney review: ToS, Privacy Policy, Cookie Policy, DPA | `roadmap.md:148`, `docs/legal/` | Legal |
| B3 | Doplnit Privacy Policy: encryption at rest (§7), anonymization (§4.3) | `docs/legal/PRIVACY_POLICY.md` | Legal |
| B4 | Doplnit DPA: sub-processor list (§4.4), public `/legal/subprocessors` page | `docs/legal/DPA_TEMPLATE.md` | Legal + Engineering |
| B5 | Vyplnit pricing URL placeholders v legal docs | `docs/legal/` | Engineering |
| B6 | Nastavit PyPI environment protection rule v GitHub | `.github/workflows/publish.yml` | Engineering |
| B7 | Ověřit a nastavit email adresy: `security@`, `legal@`, `sales@engramia.dev` | `roadmap.md:154` | Ops |
| B8 | Definovat a implementovat cloud signup/onboarding flow | `docs/user-guide.md` Sec. 2 | Product + Engineering |
| B9 | IP ownership / employment contract legal review | `roadmap.md:160` | Legal |
| B10 | LICENSE.txt structural fix per BSL 1.1 boilerplate | `LICENSE.txt` | Engineering |

### IMPORTANT — mělo by být hotovo, ne-blocking pro soft launch

| # | Položka | Lokace v repo | Owner |
|---|---|---|---|
| I1 | Přidat resource limits do docker-compose.prod.yml pro API + PG | `docker-compose.prod.yml` | Engineering |
| I2 | Přidat SAST + dependency scan do CI | `.github/workflows/ci.yml` | Engineering |
| I3 | Přidat PostgreSQL integration testy do CI | `.github/workflows/ci.yml` | Engineering |
| I4 | Vytvořit `scripts/backup.sh` + cron setup | `scripts/` | Engineering |
| I5 | Přidat robots.txt + sitemap.xml do website | `website/website/public/` | Engineering |
| I6 | Přidat Open Graph + Twitter card meta tagy | `website/website/src/app/layout.tsx` | Engineering |
| I7 | Expozovat status page na public URL | `Caddyfile`, `docker-compose.monitoring.yml` | Ops |
| I8 | Vytvořit technický support kanál | — | Product |
| I9 | Doplnit User Guide: webhooks, audit log, key rotation, expires_at, DSR | `docs/user-guide.md` | Engineering |
| I10 | Opravit 008 migration docstring "Revises: 007" → "006" | `engramia/db/migrations/versions/008_billing.py` | Engineering |
| I11 | Přidat UAT scénáře pro OIDC SSO flow | `docs/uat.md` | Engineering |
| I12 | Přidat MRR/churn/active-tenants panel do Grafana | `monitoring/grafana/` | Engineering |
| I13 | Stripe payment failure → alerting (Slack/email) | `engramia/billing/webhooks.py` | Engineering |
| I14 | Změnit mypy na blokující nebo odstranit | `.github/workflows/ci.yml` | Engineering |

### NICE-TO-HAVE — může počkat na post-launch

| # | Položka | Lokace v repo |
|---|---|---|
| N1 | Custom branded 404 page na website | `website/website/src/app/not-found.tsx` |
| N2 | GitHub feature request template | `.github/ISSUE_TEMPLATE/feature_request.yml` |
| N3 | UAT testy pro LangChain/CrewAI/MCP SDK integrace | `docs/uat.md` |
| N4 | In-app feedback / NPS mechanismus | — |
| N5 | Product Hunt / HN launch post draft | — |
| N6 | Webhook notifications pro events (Slack/Discord) | `roadmap.md:181` |
| N7 | YAML config file alternativa | `roadmap.md:182` |
| N8 | Guided "5-minute integration" tutorial | `docs/user-guide.md` |
| N9 | External secret management (Vault/KMS) | `roadmap.md:188` |
| N10 | Staging deploy workflow pro PR previews | `.github/workflows/` |

---

**Celkové skóre: ~87/100** (posun z 78 → 83 → 87 přes 3 audit cykly). Technicky je projekt na velmi dobré úrovni pro single-VM MVP launch. Zbývající blocking body jsou převážně business/legal: attorney review, email setup, cloud onboarding UX, IP ownership. Z čistě engineering perspective je systém production-ready.
