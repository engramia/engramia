# UAT Checklist — Engramia (Pre-Launch Production Testing)

> Uzavřené produkční testování před public release.
> Každý krok označte `[x]` po úspěšném ověření. Neúspěšné kroky označte `[F]` a zdokumentujte odchylku.

---

## Předpoklady

Před zahájením testování musí být připraveno:

### Infrastruktura
- [ ] Staging prostředí běží na PostgreSQL (ne JSON storage)
- [ ] Všechny DB migrace proběhly (`alembic upgrade head`)
- [ ] LLM provider (OpenAI) dostupný a API klíč platný
- [ ] Embedding model dostupný (`text-embedding-3-small`)

### Stripe (Billing)
- [ ] Stripe account v **test mode** (`sk_test_...`)
- [ ] `STRIPE_SECRET_KEY=sk_test_...` nastaven
- [ ] `STRIPE_WEBHOOK_SECRET=whsec_...` nastaven (z Stripe Dashboard → Webhooks)
- [ ] Stripe CLI nainstalován pro lokální webhook forwarding: `stripe listen --forward-to <host>/v1/billing/webhook`
- [ ] Testovací produkty a ceny vytvořeny v Stripe (sandbox/pro/team price_id)
- [ ] Testovací karty připraveny:
  - `4242 4242 4242 4242` — úspěšná platba
  - `4000 0000 0000 0002` — platba odmítnuta
  - `4000 0025 0000 3155` — vyžaduje 3DS autentizaci
  - `4000 0000 0000 9995` — insufficient funds
- [ ] `ENGRAMIA_BOOTSTRAP_TOKEN` nastaven (min. 32 náhodných znaků)

### Auth
- [ ] `ENGRAMIA_AUTH_MODE=db` nastaven
- [ ] Databáze čistá (prázdná tabulka `api_keys`) před bootstrap testem

### Monitoring
- [ ] `ENGRAMIA_METRICS=true` nastaven
- [ ] Přístup k aplikačním logům (stdout/journald)
- [ ] HTTP klient připraven (curl / Postman / httpie)

### Test data
- [ ] Připraveny testovací e-maily pro DSR (GDPR) scénáře
- [ ] Testovací JSON payload pro `/v1/learn` (task, code, eval_score, output)

---

## 1. Auth & Registration

### 1.1 Bootstrap — první spuštění

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 1.1.1 | [ ] `POST /v1/keys/bootstrap` s platným `bootstrap_token`, `tenant_name`, `project_name`, `key_name` | HTTP 200, vrátí `key` (owner role), `tenant_id`, `project_id` |
| 1.1.2 | [ ] Zopakujte stejný požadavek znovu | HTTP 409 Conflict — klíče již existují |
| 1.1.3 | [ ] `POST /v1/keys/bootstrap` se špatným `bootstrap_token` | HTTP 401 nebo 403 |
| 1.1.4 | [ ] `POST /v1/keys/bootstrap` bez těla | HTTP 422 Unprocessable Entity |

### 1.2 Správa API klíčů

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 1.2.1 | [ ] `POST /v1/keys` (owner token) — vytvoř editor klíč (`role=editor`) | HTTP 200, vrátí `key` jednou (znovu nezobrazitelný) |
| 1.2.2 | [ ] `POST /v1/keys` (admin token) — vytvoř editor klíč | HTTP 200 |
| 1.2.3 | [ ] `POST /v1/keys` (admin token) — pokus o vytvoření admin klíče | HTTP 403 — admin nemůže přiřadit admin roli |
| 1.2.4 | [ ] `POST /v1/keys` (editor token) | HTTP 403 — editor nemá oprávnění |
| 1.2.5 | [ ] `GET /v1/keys` (admin token) | HTTP 200, seznam obsahuje vytvořené klíče |
| 1.2.6 | [ ] `GET /v1/keys` (editor token) | HTTP 403 |
| 1.2.7 | [ ] `DELETE /v1/keys/{key_id}` (admin token) — revokuj editor klíč | HTTP 200, `revoked: true` |
| 1.2.8 | [ ] Použij právě revokovaný klíč pro libovolný autentizovaný endpoint | HTTP 401 (cache invalidace musí proběhnout okamžitě) |
| 1.2.9 | [ ] `DELETE /v1/keys/{key_id}` na již revokovaný klíč | HTTP 409 Already Revoked |
| 1.2.10 | [ ] `POST /v1/keys/{key_id}/rotate` (admin token) | HTTP 200, vrátí nový `key` a nový `key_prefix` |
| 1.2.11 | [ ] Použij starý klíč po rotaci | HTTP 401 |
| 1.2.12 | [ ] Použij nový klíč po rotaci | HTTP 200 na chráněném endpointu |
| 1.2.13 | [ ] `POST /v1/keys` s `expires_at` v minulosti | HTTP 422 nebo klíč odmítnut při prvním použití |
| 1.2.14 | [ ] Vytvoř klíč s `expires_at` v blízké budoucnosti, počkej na vypršení, použij klíč | HTTP 401 |

### 1.3 Autentizace — obecné

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 1.3.1 | [ ] Zavolej chráněný endpoint bez `Authorization` headeru | HTTP 401, `reason: missing_or_malformed_header` v audit logu |
| 1.3.2 | [ ] Zavolej chráněný endpoint s náhodným tokenem | HTTP 401, `reason: invalid_key` v audit logu |
| 1.3.3 | [ ] Zavolej chráněný endpoint s `Authorization: Bearer ` (prázdný token) | HTTP 401 |
| 1.3.4 | [ ] Ověř, že `GET /v1/version` odpovídá **bez** autentizace | HTTP 200, vrátí `app_version`, `api_version` |
| 1.3.5 | [ ] Ověř, že `POST /v1/billing/webhook` přijímá požadavky bez Bearer tokenu (Stripe podpis místo auth) | HTTP 200 (s platnou Stripe signature) |

### 1.4 RBAC — přístupová oprávnění

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 1.4.1 | [ ] Reader token → `GET /v1/metrics` | HTTP 200 |
| 1.4.2 | [ ] Reader token → `POST /v1/learn` | HTTP 403 |
| 1.4.3 | [ ] Editor token → `POST /v1/learn` | HTTP 200 |
| 1.4.4 | [ ] Editor token → `GET /v1/keys` | HTTP 403 |
| 1.4.5 | [ ] Admin token → `DELETE /v1/governance/tenants/{tenant_id}` | HTTP 403 (pouze owner) |
| 1.4.6 | [ ] Owner token → `DELETE /v1/governance/tenants/{tenant_id}` | HTTP 200 (nebo 204) |

---

## 2. Core API — Learn / Recall / Evaluate / Compose

### 2.1 Learn (ukládání patterns)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.1.1 | [ ] `POST /v1/learn` s platným payloadem (`task`, `code`, `eval_score`, `output`) | HTTP 200, `stored: true`, `pattern_count >= 1` |
| 2.1.2 | [ ] Opakuj 5× s různými úkoly | Každý vrátí `stored: true`; pattern_count roste |
| 2.1.3 | [ ] `POST /v1/learn` s `classification: confidential` | HTTP 200; pattern se uloží s tímto štítkem |
| 2.1.4 | [ ] `POST /v1/learn` bez povinných polí (`task` chybí) | HTTP 422 |
| 2.1.5 | [ ] `POST /v1/learn` s tělem > 1 MB | HTTP 413 Payload Too Large |
| 2.1.6 | [ ] Reader token → `POST /v1/learn` | HTTP 403 |

### 2.2 Recall (sémantické vyhledávání)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.2.1 | [ ] `POST /v1/recall` s `task` shodným s dříve uloženým | HTTP 200, `matches` obsahuje relevantní výsledky |
| 2.2.2 | [ ] `POST /v1/recall` s `limit: 3`, `offset: 0` | HTTP 200, max 3 výsledky; `has_more` reflektuje realitu |
| 2.2.3 | [ ] `POST /v1/recall` s `offset` pro stránkování | HTTP 200, vrátí sadu bez překryvu s předchozí stránkou |
| 2.2.4 | [ ] `POST /v1/recall` s `classification: confidential` | HTTP 200, vrátí pouze confidential patterns |
| 2.2.5 | [ ] `POST /v1/recall` s `min_score: 0.9` | HTTP 200, vrátí pouze výsledky s score ≥ 0.9 |
| 2.2.6 | [ ] `POST /v1/recall` s `deduplicate: true` | HTTP 200, žádné duplicitní patterns ve výsledcích |

### 2.3 Evaluate

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.3.1 | [ ] `POST /v1/evaluate` s platným payloadem | HTTP 200, `median_score` ∈ [0, 10], `feedback` neprázdný |
| 2.3.2 | [ ] `POST /v1/evaluate` s `num_evals: 5` | HTTP 200, `scores` má 5 prvků |
| 2.3.3 | [ ] `POST /v1/evaluate` s `num_evals: 0` nebo `num_evals: 11` | HTTP 422 (mimo rozsah 1–10) |
| 2.3.4 | [ ] `POST /v1/evaluate` s `Prefer: respond-async` | HTTP 202, tělo obsahuje `job_id`, header `Location: /v1/jobs/{job_id}` |
| 2.3.5 | [ ] `GET /v1/jobs/{job_id}` z předchozího kroku | HTTP 200, status `pending` → `running` → `completed` |
| 2.3.6 | [ ] Ověř, že po úspěšném evaluaci se inkrementuje `eval_runs` v billingových datech | `GET /v1/billing/status` vrátí `eval_runs_used` o 1 vyšší |
| 2.3.7 | [ ] Reader token → `POST /v1/evaluate` | HTTP 403 |

### 2.4 Compose

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.4.1 | [ ] `POST /v1/compose` s task (po naučení ≥2 patterns) | HTTP 200, `stages` neprázdný, `valid: true` |
| 2.4.2 | [ ] `POST /v1/compose` s `Prefer: respond-async` | HTTP 202, `job_id` v odpovědi |
| 2.4.3 | [ ] `POST /v1/compose` s prázdnou databází patterns | HTTP 200, `stages: []` nebo `valid: false` |

### 2.5 Evolve & Analyze Failures

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.5.1 | [ ] `POST /v1/evolve` s `role`, `current_prompt` | HTTP 200, `improved_prompt` neprázdný, `changes` vyplněny |
| 2.5.2 | [ ] `POST /v1/evolve` s `Prefer: respond-async` | HTTP 202 |
| 2.5.3 | [ ] `POST /v1/analyze-failures` po naučení pattern se špatným eval_score | HTTP 200, `clusters` obsahuje cluster se skupinami chyb |

### 2.6 Pattern Management

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.6.1 | [ ] `DELETE /v1/patterns/{pattern_key}` (admin token) — smaž cizí pattern | HTTP 200, `deleted: true` |
| 2.6.2 | [ ] `DELETE /v1/patterns/{pattern_key}` (editor token) — smaž vlastní pattern | HTTP 200, `deleted: true` |
| 2.6.3 | [ ] `DELETE /v1/patterns/{pattern_key}` (editor token) — smaž cizí pattern | HTTP 403 |
| 2.6.4 | [ ] `GET /v1/export` (admin token) | HTTP 200, `records` obsahuje uložené patterns, `count` sedí |
| 2.6.5 | [ ] `POST /v1/import` (admin token) — importuj záznamy z exportu | HTTP 200, `imported` = počet importovaných |
| 2.6.6 | [ ] `POST /v1/import` s `overwrite: false` na existující klíč | HTTP 200, existující klíč přeskočen |
| 2.6.7 | [ ] `POST /v1/import` bez `patterns/` prefixu u klíčů | HTTP 200, malformovaný záznam přeskočen |

### 2.7 Skills

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.7.1 | [ ] `POST /v1/skills/register` s existujícím `pattern_key` a `skills: ["parsing", "sql"]` | HTTP 200, `registered: 2` |
| 2.7.2 | [ ] `POST /v1/skills/search` s `required: ["parsing"]` | HTTP 200, výsledky obsahují zaregistrovaný pattern |
| 2.7.3 | [ ] `POST /v1/skills/search` s `required: ["parsing", "sql"], match_all: true` | HTTP 200, vrátí pouze patterns s oběma tagy |

### 2.8 Feedback & Metrics

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.8.1 | [ ] `GET /v1/feedback` | HTTP 200, `feedback` obsahuje opakující se chyby (nebo prázdný seznam) |
| 2.8.2 | [ ] `GET /v1/feedback?task_type=parsing&limit=3` | HTTP 200, max 3 výsledky filtrované podle task_type |
| 2.8.3 | [ ] `GET /v1/metrics` | HTTP 200, `runs`, `success_rate`, `avg_eval_score`, `pattern_count` vyplněny |

### 2.9 Health & Version

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.9.1 | [ ] `GET /v1/health` | HTTP 200, `status: "ok"` |
| 2.9.2 | [ ] `GET /v1/health/deep` | HTTP 200, všechny tři checks (`storage`, `llm`, `embedding`) se statusem a `latency_ms` |
| 2.9.3 | [ ] `GET /v1/version` (bez auth) | HTTP 200, `app_version` a `api_version` vyplněny |
| 2.9.4 | [ ] Zastav embedding provider, zavolej `GET /v1/health/deep` | HTTP 503 nebo 200 s `status: degraded`, `embedding.status: error` |

### 2.10 Async Jobs

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 2.10.1 | [ ] `GET /v1/jobs` | HTTP 200, seznam jobů pro aktuální projekt |
| 2.10.2 | [ ] `GET /v1/jobs/{job_id}` na existující job | HTTP 200, správný status |
| 2.10.3 | [ ] `GET /v1/jobs/{job_id}` na neexistující UUID | HTTP 404 |
| 2.10.4 | [ ] `POST /v1/jobs/{job_id}/cancel` na pending job | HTTP 200, status se změní na `cancelled` |
| 2.10.5 | [ ] `POST /v1/jobs/{job_id}/cancel` na completed job | HTTP 409 nebo 400 |
| 2.10.6 | [ ] Reader token → `POST /v1/jobs/{job_id}/cancel` | HTTP 403 |

---

## 3. Billing — Subscription, Checkout, Portal, Overage, Dunning

### 3.1 Billing Status (sandbox mode)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 3.1.1 | [ ] `GET /v1/billing/status` bez Stripe konfigurace | HTTP 200, `plan_tier: "sandbox"`, limity `null` |
| 3.1.2 | [ ] `GET /v1/billing/status` se Stripe konfigurací (po bootstrap) | HTTP 200, `plan_tier: "sandbox"`, `eval_runs_used` a `patterns_used` mají číselné hodnoty |

### 3.2 Checkout — nová subscription

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 3.2.1 | [ ] `POST /v1/billing/checkout` s platným `price_id` (pro sandbox plán), `success_url`, `cancel_url` | HTTP 200, `checkout_url` ukazuje na `checkout.stripe.com` |
| 3.2.2 | [ ] Otevři `checkout_url` v prohlížeči, zadej testovací kartu `4242 4242 4242 4242`, dokonči platbu | Přesměrování na `success_url`; Stripe odešle `customer.subscription.created` webhook |
| 3.2.3 | [ ] Ověř, že webhook `customer.subscription.created` byl zpracován | `GET /v1/billing/status` vrátí `plan_tier: "pro"` (nebo objednaný tier), `status: "active"` |
| 3.2.4 | [ ] `POST /v1/billing/checkout` s neexistujícím `price_id` | HTTP 400 nebo Stripe chyba |

### 3.3 Customer Portal

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 3.3.1 | [ ] `GET /v1/billing/portal` (tenant se subscription) | HTTP 200, `portal_url` ukazuje na Stripe Customer Portal |
| 3.3.2 | [ ] `GET /v1/billing/portal` (tenant bez subscription, bez stripe_customer_id) | HTTP 400 |
| 3.3.3 | [ ] Otevři `portal_url`, v portálu zruš subscription | Stripe odešle `customer.subscription.deleted` webhook |
| 3.3.4 | [ ] Ověř webhook `customer.subscription.deleted` | `GET /v1/billing/status` vrátí `plan_tier: "sandbox"`, `status: "canceled"` |

### 3.4 Overage (přečerpání limitu)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 3.4.1 | [ ] `PATCH /v1/billing/overage` s `enabled: true, budget_cap_cents: 5000` (tenant na pro plánu) | HTTP 200, `overage_enabled: true`, `budget_cap_cents: 5000` |
| 3.4.2 | [ ] `PATCH /v1/billing/overage` s `enabled: true` bez budget_cap | HTTP 200, `budget_cap_cents: null` (bez stropu) |
| 3.4.3 | [ ] `PATCH /v1/billing/overage` (sandbox plán) | HTTP 400 — overage není dostupný pro sandbox |
| 3.4.4 | [ ] Vyčerpej eval_runs limit (nastav nízký limit v DB, opakuj `/v1/evaluate`) | HTTP 429 se strukturovanou chybou (`quota_exceeded`, `metric: eval_runs`, `current`, `limit`) |
| 3.4.5 | [ ] Se zapnutým overage opakuj `/v1/evaluate` po vyčerpání limitu | HTTP 200 — overage umožní pokračovat |
| 3.4.6 | [ ] Vyčerpej `budget_cap_cents`, zkus další evaluate | HTTP 429 s `error: overage_budget_cap_reached` |
| 3.4.7 | [ ] Vyčerpej pattern kvótu (nastav nízký limit), zavolej `POST /v1/learn` | HTTP 429 s `error: quota_exceeded`, `metric: patterns` |

### 3.5 Webhook — Stripe events

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 3.5.1 | [ ] `POST /v1/billing/webhook` s neplatnou `Stripe-Signature` | HTTP 400 |
| 3.5.2 | [ ] `POST /v1/billing/webhook` se správnou signaturou, event `invoice.payment_failed` | HTTP 200; `GET /v1/billing/status` vrátí `status: "past_due"` |
| 3.5.3 | [ ] Ověř grace period: `POST /v1/learn` do 7 dní od `past_due` | HTTP 200 (přístup povolen, warning v logu) |
| 3.5.4 | [ ] Nastav `past_due_since` na > 7 dní v DB, zavolej `POST /v1/learn` | HTTP 402 Payment Required |
| 3.5.5 | [ ] `POST /v1/billing/webhook` s event `invoice.paid` | HTTP 200; `status` se změní na `active`, `past_due_since` vymazán |
| 3.5.6 | [ ] Opakuj stejný webhook event (test idempotence) | HTTP 200, ale znovu nezpracuje (deduplikace via `processed_webhook_events`) |
| 3.5.7 | [ ] `POST /v1/billing/webhook` s `customer.subscription.updated` (upgrade na team) | HTTP 200; `GET /v1/billing/status` vrátí `plan_tier: "team"`, vyšší limity |
| 3.5.8 | [ ] `POST /v1/billing/webhook` s `invoice.created` | HTTP 200, overage report odeslán do Stripe (ověř v Stripe Dashboard → Invoices) |

### 3.6 Dunning (upozornění na platební problémy)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 3.6.1 | [ ] Nastav `past_due_since` na 5 dní v DB, zavolej endpoint | Audit log obsahuje `access_expiring_soon` event s `days_remaining: 2` |
| 3.6.2 | [ ] Nastav `past_due_since` na 6 dní, zavolej endpoint | Dunning log s příslušným varovným hlášením |

---

## 4. GDPR / DSR (Data Subject Requests)

### 4.1 Retention Policy

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 4.1.1 | [ ] `GET /v1/governance/retention` | HTTP 200, `retention_days: 90`, `source: "default"` |
| 4.1.2 | [ ] `PUT /v1/governance/retention` s `retention_days: 30` | HTTP 200, `retention_days: 30`, `source: "project"` |
| 4.1.3 | [ ] `GET /v1/governance/retention` po nastavení | HTTP 200, `retention_days: 30` |
| 4.1.4 | [ ] `PUT /v1/governance/retention` s `retention_days: null` | HTTP 200, `source: "tenant"` nebo `"default"` (inherit) |
| 4.1.5 | [ ] `PUT /v1/governance/retention` s `retention_days: 0` nebo `retention_days: 36501` | HTTP 422 (mimo rozsah 1–36500) |
| 4.1.6 | [ ] Editor token → `PUT /v1/governance/retention` | HTTP 403 |

### 4.2 Retention Apply (mazání starých dat)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 4.2.1 | [ ] Ulož pattern se starým `created_at` (přímo v DB), nastav `retention_days: 1` | — |
| 4.2.2 | [ ] `POST /v1/governance/retention/apply` s `dry_run: true` | HTTP 200, `purged_count > 0`, `dry_run: true`; záznamy stále existují |
| 4.2.3 | [ ] `POST /v1/governance/retention/apply` s `dry_run: false` | HTTP 200, `purged_count > 0`; záznamy jsou smazány; audit log obsahuje `retention_applied` |
| 4.2.4 | [ ] `POST /v1/governance/retention/apply` s `Prefer: respond-async` | HTTP 202, `job_id` v odpovědi |

### 4.3 GDPR Export (právo na přenositelnost — čl. 20)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 4.3.1 | [ ] `GET /v1/governance/export` | HTTP 200, streaming NDJSON, každý řádek obsahuje `version`, `key`, `data` |
| 4.3.2 | [ ] `GET /v1/governance/export?classification=confidential` | HTTP 200, vrátí pouze `confidential` záznamy |
| 4.3.3 | [ ] `GET /v1/governance/export?classification=public,internal` | HTTP 200, vrátí záznamy obou klasifikací |
| 4.3.4 | [ ] Ověř audit log | Obsahuje `data_exported` event s `count`, `tenant_id`, `key_id`, `ip` |
| 4.3.5 | [ ] Editor token → `GET /v1/governance/export` | HTTP 403 |

### 4.4 Klasifikace patterns

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 4.4.1 | [ ] `PUT /v1/governance/patterns/{pattern_key}/classify` s `classification: confidential` | HTTP 200, `classification: "confidential"` |
| 4.4.2 | [ ] `POST /v1/recall` s `classification: confidential` | HTTP 200, vrátí právě překlasifikovaný pattern |
| 4.4.3 | [ ] `PUT /v1/governance/patterns/{neexistujici_klic}/classify` | HTTP 404 |

### 4.5 Smazání projektu (právo na výmaz — čl. 17)

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 4.5.1 | [ ] `DELETE /v1/governance/projects/{project_id}` (admin token, vlastní projekt) | HTTP 200, `patterns_deleted > 0`, `keys_revoked > 0` |
| 4.5.2 | [ ] Ověř, že patterns jsou smazány: `POST /v1/recall` | HTTP 200, `matches: []` |
| 4.5.3 | [ ] `DELETE /v1/governance/projects/{cizi_project_id}` (admin token jiného projektu) | HTTP 403 |
| 4.5.4 | [ ] `DELETE /v1/governance/projects/{project_id}` (owner token) — může smazat libovolný projekt v tenantu | HTTP 200 |
| 4.5.5 | [ ] Editor token → `DELETE /v1/governance/projects/{project_id}` | HTTP 403 |

### 4.6 Smazání tenanta

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 4.6.1 | [ ] `DELETE /v1/governance/tenants/{tenant_id}` (owner token, shodný tenant) | HTTP 200, `patterns_deleted`, `projects_deleted` nenulové |
| 4.6.2 | [ ] `DELETE /v1/governance/tenants/{jiny_tenant_id}` (owner token jiného tenanta) | HTTP 403 |
| 4.6.3 | [ ] Ověř, že tenant je kompletně odstraněn: API klíče nefungují | HTTP 401 |

---

## 5. Webhooks (Stripe) — podrobné scénáře

*Použij `stripe trigger` CLI nebo Stripe Dashboard pro spouštění testovacích eventů.*

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 5.1 | [ ] Trigger: `customer.subscription.created` (sandbox→pro) | Subscription uložena v DB; `GET /v1/billing/status` vrátí `plan_tier: "pro"` |
| 5.2 | [ ] Trigger: `customer.subscription.updated` (interval: monthly→yearly) | `billing_interval` se změní v DB |
| 5.3 | [ ] Trigger: `customer.subscription.deleted` | `plan_tier` degradován na `sandbox` |
| 5.4 | [ ] Trigger: `invoice.payment_failed` | Status `past_due`, `past_due_since` nastaven |
| 5.5 | [ ] Trigger: `invoice.paid` po předchozím `payment_failed` | Status `active`, `past_due_since` vymazán |
| 5.6 | [ ] Trigger: `invoice.created` (s overage usage) | Overage jednotky reportovány do Stripe |
| 5.7 | [ ] Duplicitní event (stejné `event.id`) | HTTP 200, ale DB nezmutována (idempotence) |
| 5.8 | [ ] Webhook bez `Stripe-Signature` headeru | HTTP 400 |
| 5.9 | [ ] Webhook s pozměněným tělem (neplatná signatura) | HTTP 400 |

---

## 6. Monitoring / Observability

### 6.1 Prometheus Metrics

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 6.1.1 | [ ] `GET /metrics` (s `ENGRAMIA_METRICS=true`) | HTTP 200, text/plain Prometheus formát |
| 6.1.2 | [ ] Ověř přítomnost: `engramia_pattern_count`, `engramia_avg_eval_score`, `engramia_total_runs`, `engramia_success_rate`, `engramia_reuse_rate` | Všechny metriky přítomny s číselnými hodnotami |
| 6.1.3 | [ ] `GET /metrics` s `ENGRAMIA_METRICS_TOKEN` nastaveným, bez tokenu | HTTP 401 nebo 403 |
| 6.1.4 | [ ] `GET /metrics` bez `ENGRAMIA_METRICS=true` | HTTP 404 (endpoint není zaregistrován) |

### 6.2 Audit Log

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 6.2.1 | [ ] Zavolej endpoint s neplatným tokenem | Audit log obsahuje `auth_failure` event s `ip`, `reason` |
| 6.2.2 | [ ] Smaž pattern (admin) | Audit log obsahuje `pattern_deleted` s `pattern_key`, `tenant_id`, `key_id` |
| 6.2.3 | [ ] Proveď export (`GET /v1/export`) | Audit log obsahuje `data_exported` |
| 6.2.4 | [ ] Proveď bulk import | Audit log obsahuje `bulk_import` s `total`, `imported` |
| 6.2.5 | [ ] Zkontroluj formát audit logu | JSON objekt s `audit: true`, `event`, `timestamp` |

### 6.3 Maintenance Mode

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 6.3.1 | [ ] Nastav `ENGRAMIA_MAINTENANCE=true`, zavolej `POST /v1/learn` | HTTP 503, header `Retry-After: 3600` |
| 6.3.2 | [ ] V maintenance mode zavolej `GET /v1/health` | HTTP 200 (výjimka z maintenance) |
| 6.3.3 | [ ] V maintenance mode zavolej `GET /v1/health/deep` | HTTP 200 (výjimka z maintenance) |

---

## 7. Security — Limity, Rate Limiting, Neautorizovaný přístup

### 7.1 Rate Limiting

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 7.1.1 | [ ] Odešli > 60 požadavků/min na `/v1/recall` z jedné IP | HTTP 429 Too Many Requests, header `Retry-After: 60` |
| 7.1.2 | [ ] Odešli > 10 požadavků/min na `/v1/evaluate` z jedné IP | HTTP 429 (LLM expensive limit = 10/min) |
| 7.1.3 | [ ] Odešli > 120 požadavků/min jedním API klíčem (různé cesty) | HTTP 429 (per-key limit) |
| 7.1.4 | [ ] Ověř audit log při rate limit | Obsahuje `rate_limited` event s `ip`, `path`, `count`, `limit` |
| 7.1.5 | [ ] Po 60 sekundách pauze opakuj rate-limitovaný požadavek | HTTP 200 (okno se resetuje) |

### 7.2 Body Size Limit

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 7.2.1 | [ ] `POST /v1/learn` s tělem přesně 1 MB (1,048,576 B) | HTTP 413 Payload Too Large |
| 7.2.2 | [ ] `POST /v1/learn` s tělem < 1 MB | HTTP 200 (projde) |

### 7.3 Security Headers

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 7.3.1 | [ ] Zkontroluj response headers libovolného endpointu | Přítomny: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `X-Permitted-Cross-Domain-Policies: none` |

### 7.4 CORS

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 7.4.1 | [ ] Odešli OPTIONS preflight z nepovolené domény (bez `ENGRAMIA_CORS_ORIGINS`) | Žádný `Access-Control-Allow-Origin` header v odpovědi |
| 7.4.2 | [ ] Nastav `ENGRAMIA_CORS_ORIGINS=https://test.example.com`, odešli OPTIONS z dané domény | `Access-Control-Allow-Origin: https://test.example.com` přítomen |

### 7.5 Neautorizovaný přístup — edge cases

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 7.5.1 | [ ] Použij API klíč projektu A pro přístup k datům projektu B (cross-tenant) | HTTP 200, ale vrátí pouze data vlastního projektu (scope enforcement) |
| 7.5.2 | [ ] Pokus o SQL injection v query parametrech (např. `task_type`) | HTTP 200 nebo 422 — žádná DB chyba, žádný leak |
| 7.5.3 | [ ] Timing útok: porovnej dobu odpovědi pro neexistující vs. existující API klíč (10 požadavků každého) | Střední doby odpovědi srovnatelné (timing-safe comparison) |
| 7.5.4 | [ ] `GET /v1/keys` s klíčem jiného projektu ve stejném tenantu (admin role) | Vrátí pouze klíče vlastního projektu |

### 7.6 Quota & Billing Security

| # | Akce | Očekávaný výsledek |
|---|------|-------------------|
| 7.6.1 | [ ] Nastav `max_patterns: 3` na klíč (legacy), ulož 3 patterns, zkus 4. | HTTP 429 quota exceeded |
| 7.6.2 | [ ] Přístup po zrušení subscription (`status: canceled`) | HTTP 403 Forbidden |
| 7.6.3 | [ ] Přístup po grace period vyprší (`status: past_due`, > 7 dní) | HTTP 402 Payment Required |

---

## Výsledkový přehled

Po dokončení testování vyplňte:

| Oblast | Celkem kroků | Prošlo | Selhalo | Blokující? |
|--------|-------------|--------|---------|------------|
| 1. Auth & Registration | 25 | | | |
| 2. Core API | 35 | | | |
| 3. Billing | 28 | | | |
| 4. GDPR / DSR | 22 | | | |
| 5. Webhooks (Stripe) | 9 | | | |
| 6. Monitoring | 9 | | | |
| 7. Security | 18 | | | |
| **Celkem** | **146** | | | |

### Kritéria pro release

- [ ] Všechny kroky označené jako "blokující" jsou `[x]`
- [ ] Žádný HTTP 5xx na happy-path scénářích
- [ ] Billing quota enforcement funguje pro všechny plány
- [ ] GDPR delete flow kompletně maže data (ověřeno přímým dotazem do DB)
- [ ] Stripe webhook idempotence ověřena
- [ ] Audit log zachycuje všechny security eventy
- [ ] Rate limiting aktivní na všech LLM endpointech
