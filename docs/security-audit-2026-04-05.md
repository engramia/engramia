# Security Audit — Engramia (agent-brain)

**Datum:** 2026-04-05
**Auditor:** Interní bezpečnostní review (full source analysis)
**Verze projektu:** 0.6.5
**Rozsah:** Full-stack audit vs. SOC 2 Type II, ISO 27001:2022, GDPR/DSGVO, OWASP Top 10 (2021), OWASP API Security Top 10, CIS Controls v8, PCI DSS
**Základ analýzy:** Zdrojový kód (`engramia/api/`, `engramia/billing/`, `engramia/governance/`), CI/CD pipeline (`.github/workflows/`), dokumentace (`docs/`), právní dokumenty (`docs/legal/`), `docker-compose.prod.yml`, předchozí audit výsledky (`AUDIT_RESULTS_*.md`, `prelaunch-audit-2026-04-05.md`)
**Klasifikace:** Internal — sdílet s enterprise zákazníky pouze pod NDA

---

## 1. Executive Summary

| Standard | Status | Skóre | Klíčový gap |
|----------|--------|-------|-------------|
| **GDPR / DSGVO** | 🟡 | 72 % | Chybí RoPA, DPIA, IRP/Art.33, SCCs pro US sub-procesory |
| **SOC 2 Type II** | 🟡 | 74 % | Chybí formální IRP, capacity limits, SoD politika, security training |
| **OWASP Top 10 (2021)** | 🟢 | 88 % | A06 jen částečně (SBOM chybí); SSRF neošetřen (A10) |
| **OWASP API Security Top 10** | 🟢 | 80 % | SSRF pro webhook URL (API7); distribuovaný rate limit (API4) |
| **ISO 27001:2022** | 🟡 | 66 % | Chybí formální ISMS, IRP, asset register, role CISO |
| **CIS Controls v8** | 🟡 | 70 % | IG1: 87 % (silné), IG2: 47 % (gaps v MFA, pen test, at-rest encryption) |
| **PCI DSS (SAQ A)** | 🟢 | 85 % | Scope správně minimalizován přes Stripe; chybí formální IRP + awareness |

### Celkové hodnocení

Engramia má **nadstandardně silný technický security základ** pro pre-launch fázi:

- ✅ Timing-safe autentizace, SHA-256 klíče, RBAC hierarchie
- ✅ Multi-tenancy izolace přes contextvars + DB scope
- ✅ PII redakce pipeline výchozí zapnuta
- ✅ Duální audit log (JSON + PostgreSQL) + Loki forwarding
- ✅ GDPR tooling kompletní (DSR, mazání, export, retence)
- ✅ CI/CD s pip-audit + TruffleHog
- ✅ Stripe-hosted platby — žádná karta neprochází serverem

**Zbývající mezery jsou primárně procesní a dokumentační** — RoPA, DPIA, IRP, formální politiky. Žádná zásadní architekturální přepracování nejsou potřeba.

**Stav po předchozích auditech:** 78/100 (2026-03-28) → 83/100 (2026-04-02) → 87/100 (2026-04-04). Trend je pozitivní; tento report přidává rozměr standardů compliance.

---

## 2. GDPR / DSGVO — Detailní Analýza

> Jsme v ČR (EU), zpracováváme data EU subjektů, používáme US sub-procesory. GDPR compliance je kritická pro každého zákazníka.

### 2.1 Zákonný Základ a Souhlas

| Požadavek | Článek | Status | Evidence |
|-----------|--------|--------|----------|
| Zákonný základ zpracování | Art. 6 | ✅ | ToS (smluvní plnění) + Privacy Policy |
| Souhlas pro cookies | Art. 7 | ✅ | `docs/legal/COOKIE_POLICY.md` existuje |
| Informační povinnost vůči subjektům | Art. 13/14 | 🟡 | Privacy Policy existuje — **potřebuje právní review** |
| Účel zpracování jasně definován | Art. 5(1)(b) | ✅ | `docs/data-handling.md` + ToS |
| Minimalizace dat | Art. 5(1)(c) | ✅ | PII redakce, datová klasifikace v `data-handling.md` |

### 2.2 Práva Subjektů Údajů

| Právo | Článek | Status | Evidence | Mezera |
|-------|--------|--------|----------|--------|
| Přístup k datům | Art. 15 | ✅ | `governance/dsr.py` typ `access` | — |
| Oprava dat | Art. 16 | ✅ | DSR typ `rectification` | — |
| Výmaz ("být zapomenut") | Art. 17 | ✅ | `governance/deletion.py` — kaskádové mazání (storage → jobs → keys → audit → projects) | Audit log řádky nejsou smazány, pouze scrubbed — správný přístup |
| Přenositelnost dat | Art. 20 | ✅ | NDJSON export via `governance/export.py` + API endpoint | — |
| Omezení zpracování | Art. 18 | ❌ | Není implementováno | Přidat DSR typ `restriction` |
| Námitka proti zpracování | Art. 21 | ❌ | Žádný mechanismus opt-out | Zdokumentovat scope (netýká se čistě smluvního zpracování) |
| Automatizované rozhodování | Art. 22 | N/A | Není relevantní pro aktuální use-case | — |

**DSR SLA:** 30 dní default (konfigurovatelné `ENGRAMIA_DSR_SLA_DAYS`) ✅
**DSR tracking:** PostgreSQL tabulka `dsr_requests` + overdue detection ✅
**DSR workflow v dokumentaci:** Chybí end-to-end operátorský návod ⚠️

### 2.3 Povinnosti Zpracovatele

| Požadavek | Článek | Status | Evidence | Mezera |
|-----------|--------|--------|----------|--------|
| Záznamy o zpracování (RoPA) | Art. 30 | ❌ | Neexistuje | **Kritické — vytvořit před spuštěním** |
| Smlouva se sub-procesory | Art. 28 | 🟡 | `docs/legal/DPA_TEMPLATE.md` existuje | Potřebuje legal review; verze pro zákazníky jako správce |
| Bezpečnostní opatření | Art. 32 | 🟡 | TLS, RBAC, audit log ✅; šifrování v klidu ❌ | Viz F6 |
| Oznamování porušení ÚOOÚ | Art. 33 | ❌ | Žádný formální IRP s 72h notifikací | **Kritické — vytvořit IRP** |
| Notifikace subjektů o porušení | Art. 34 | ❌ | Chybí proces | Součást IRP |
| DPIA pro riziková zpracování | Art. 35 | ❌ | DPIA nebyla provedena | Povinná pro AI zpracování osobních dat |
| DPO jmenování | Art. 37 | ⚠️ | Neposouzeno | Pravděpodobně nepovinnné pro malou firmu — zdokumentovat rozhodnutí |

### 2.4 Mezinárodní Předávání Dat

| Sub-procesor | Země | Transfer mechanismus | Status |
|--------------|------|---------------------|--------|
| Hetzner Cloud | DE (EU) | V rámci EU — SCCs nepotřeba | ✅ |
| OpenAI | USA | EU-US Data Privacy Framework + SCCs | ⚠️ Není zdokumentováno v PP/DPA |
| Anthropic | USA | EU-US DPF + SCCs | ⚠️ Není zdokumentováno |
| Stripe | USA/EU | EU-US DPF + SCCs (Stripe má EU entitu) | ⚠️ Není zdokumentováno |

**Akce:** Doplnit seznam transfer mechanismů do Privacy Policy sekce "International Transfers" a do DPA Annex. OpenAI a Anthropic mají veřejně dostupné SCCs — stačí je referencovat.

### 2.5 Data Retention

| Kategorie | Retence | Implementace |
|-----------|---------|--------------|
| Patterns (expired) | Dle `expires_at` | ✅ `lifecycle.py:cleanup_expired_patterns()` |
| Audit log | 90 dní | ✅ `lifecycle.py:compact_audit_log()` — **pro enterprise zvýšit na 2 roky** |
| Jobs | 30 dní po dokončení | ✅ `lifecycle.py:cleanup_old_jobs()` |
| DSR záznamy | Nedefinováno | ⚠️ Přidat retenci (doporučeno 5 let pro compliance) |
| Billing data | Dle Stripe | ✅ Stripe uchovává dle vlastních politik |

### 2.6 Privacy by Design (Art. 25)

- PII redakce pipeline výchozí zapnuta (`ENGRAMIA_REDACTION=true`) ✅
- Datová klasifikace: PUBLIC / INTERNAL / CONFIDENTIAL ✅
- Tenant izolace přes contextvars + DB scope ✅
- Pouze SHA-256 hash API klíčů v DB (nikdy plain text) ✅
- Redakce PII v audit logu při mazání ✅

### 2.7 GDPR Souhrnné Skóre

**Splněno:** 13/21 požadavků (62 %)
**Kritické mezery (4):** RoPA, DPIA, IRP/Art.33, SCCs dokumentace
**Střední priority (3):** DPO posouzení, Art. 18 omezení, DSR retence
**Po Fázi 1 remediation:** ~17/21 (81 %)

---

## 3. SOC 2 Type II — Gap Analysis

### 3.1 CC1 — Control Environment

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| CC1.1 Integrity & ethics policies | ✅ | SECURITY.md, CONTRIBUTING.md | — |
| CC1.2 Board oversight | N/A | Startup fáze | — |
| CC1.3 Organizational structure | ⚠️ | Neformální | Chybí org chart + definované odpovědnosti |
| CC1.4 Commitment to competence | ❌ | Žádný security training program | Vytvořit security awareness onboarding |
| CC1.5 Accountability enforcement | ❌ | Žádné disciplinární politiky | Minimální: zdokumentovat v HR/founder docs |

### 3.2 CC2 — Communication and Information

| Kontrola | Status | Evidence |
|----------|--------|----------|
| CC2.1 Interní komunikace | ✅ | CLAUDE.md, CONTRIBUTING.md, runbooks |
| CC2.2 Externí komunikace o bezpečnosti | ✅ | SECURITY.md, Privacy Policy, `security@engramia.dev` |
| CC2.3 Komunikace rizik | ✅ | AUDIT_RESULTS_*.md, prelaunch-audit, threat model v SECURITY.md |

### 3.3 CC3 — Risk Assessment

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| CC3.1 Identifikace rizik | ✅ | SECURITY.md threat model, opakované audit cykly | — |
| CC3.2 Analýza rizik | ✅ | Skóre 78→83→87/100 přes 3 audit cykly | — |
| CC3.3 Risk response | 🟡 | Informální roadmap v audit docs | Formalizovat risk register s vlastníky |
| CC3.4 Change risk assessment | ❌ | Žádný formální change advisory board | Minimální: checklist v PR template |

### 3.4 CC6 — Logical and Physical Access Controls

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| CC6.1 Access control politika | ✅ | RBAC v `permissions.py`, `auth.py` | — |
| CC6.2 Autentizace | ✅ | Timing-safe `hmac.compare_digest()`, multi-mode auth, SHA-256 | — |
| CC6.3 Autorizace | ✅ | Role hierarchie `reader ⊂ editor ⊂ admin ⊂ owner`, per-endpoint guards | — |
| CC6.6 Least privilege | ✅ | RBAC s minimálními výchozími oprávněními, admin nemůže přiřadit owner roli | — |
| CC6.7 Remote access | ✅ | TLS přes Caddy (Let's Encrypt), SSH deploy key | — |
| CC6.8 Malware protection | ❌ | Žádný AV/EDR na produkčním serveru | Zvážit ClamAV nebo cloudový endpoint protection |

### 3.5 CC7 — System Operations

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| CC7.1 Vulnerability management | 🟡 | `pip-audit --strict` + TruffleHog v CI | Chybí SAST, runtime SCA, SBOM |
| CC7.2 Security monitoring | ✅ | Prometheus + Grafana + Loki + Alertmanager + Uptime Kuma | — |
| CC7.3 Incident response | ⚠️ | 12 operačních runbooks existuje | **Formální IRP (detekce → klasifikace → izolace → notifikace → obnova) chybí** |
| CC7.4 Incident classification | ❌ | Žádná severity klasifikace (P0/P1/P2/P3) | — |
| CC7.5 Recovery | ✅ | DR plán s RTO 4h, RPO 24h, `docs/disaster-recovery.md` | Backup není automatizován |

### 3.6 CC8 — Change Management

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| CC8.1 Change authorization | ✅ | GitHub PRs, CI required checks, branch protection | — |
| CC8.2 Change documentation | ✅ | CHANGELOG.md, lineární Alembic migrace 001→012 | — |
| CC8.3 Testing | ✅ | 80.29% coverage, vynucený threshold v CI | — |
| CC8.4 Segregation of duties | ❌ | Žádná formální SoD politika | Dokumentovat kdo co může schválit |
| CC8.5 Rollback | ✅ | Alembic downgrade, deployment runbook | — |

### 3.7 A1 — Availability

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| A1.1 Capacity planning | ❌ | `docker-compose.prod.yml` — žádné resource limits na kontejnerech | **Přidat CPU/memory limits** |
| A1.2 Environment monitoring | ✅ | Health checks na všech services, Uptime Kuma | — |
| A1.3 Recovery planning | ✅ | DR dokument, RTO/RPO definovány | — |
| A1.4 Backups | ⚠️ | Backup skripty existují v `scripts/`; nejsou automatizovány | **Automatizovat cron backup** |

### 3.8 PI1 — Processing Integrity

| Kontrola | Status | Evidence |
|----------|--------|----------|
| PI1.1 Data validation | ✅ | Pydantic schemas, eval_score bounds [0,1], task/code/num_evals caps |
| PI1.2 Processing completeness | ✅ | Job tracking + status monitoring (`pending/running/done/failed`) |
| PI1.3 Error handling | ✅ | Strukturované error responses, audit log na failures |
| PI1.4 Output validation | ✅ | LLM response truncation na 20 000 chars (`ENGRAMIA_MAX_LLM_RESPONSE`) |

### 3.9 C1 — Confidentiality

| Kontrola | Status | Evidence |
|----------|--------|----------|
| C1.1 Identifikace důvěrných dat | ✅ | Klasifikace PUBLIC/INTERNAL/CONFIDENTIAL v `data-handling.md` |
| C1.2 Omezení přístupu | ✅ | RBAC + tenant izolace přes contextvars |
| C1.3 Bezpečná likvidace dat | ✅ | Kaskádové mazání, `lifecycle.py` |

### 3.10 P — Privacy (Trust Service Criterion)

| Kontrola | Status | Evidence | Gap |
|----------|--------|----------|-----|
| P1 Notice | ✅ | Privacy Policy v `docs/legal/PRIVACY_POLICY.md` | Legal review |
| P2 Choice/Consent | ✅ | Cookie Policy, opt-in model | — |
| P3 Collection | ✅ | Minimalizace dat zdokumentována | — |
| P4 Use | ✅ | ToS definuje povolené použití dat | — |
| P5 Retention | ✅ | Retention policies implementovány v `governance/retention.py` | — |
| P6 Disclosure | ✅ | Sub-procesor seznam v `data-handling.md` | SCCs chybí |
| P7 Quality | ✅ | Rectification via DSR | — |
| P8 Monitoring/enforcement | ❌ | Žádný privacy monitoring program | — |

### 3.11 SOC 2 Souhrnné Skóre

**Splněno:** ~29/39 kontrol (74 %)
**Top 5 mezer:** Formální IRP, capacity planning, SoD politika, security awareness training, privacy monitoring
**Po Fázi 1 remediation:** ~33/39 (85 %)

---

## 4. OWASP Top 10 (2021) — Per-Item Status

| # | Kategorie | Status | Evidence | Zbývající mezera |
|---|-----------|--------|----------|-----------------|
| **A01** | Broken Access Control | ✅ **Splněno** | RBAC v `permissions.py`, `require_permission()` na každém endpointu, tenant izolace via contextvars, PostgreSQL advisory locks pro race conditions | Ověřit list endpoints pro přesnou tenant izolaci |
| **A02** | Cryptographic Failures | 🟡 **Částečné** | TLS přes Caddy (Let's Encrypt), SHA-256 pro API klíče, PyJWT pro OIDC, `hmac.compare_digest()` timing-safe | **Šifrování dat v klidu chybí** (F6) |
| **A03** | Injection | ✅ **Splněno** | SQLAlchemy parameterized queries, LIKE wildcard escaping, XML delimitery pro prompt injection, path traversal prevence (patterns/ prefix, no `..`) | Prompt injection je LLM-fundamentální — mitigováno, neodstraněno |
| **A04** | Insecure Design | ✅ **Splněno** | Multi-mode auth s bezpečnými výchozími hodnotami, explicitní opt-in pro nebezpečné konfigurace (`ENGRAMIA_ALLOW_NO_AUTH`), startup diagnostika | — |
| **A05** | Security Misconfiguration | 🟡 **Částečné** | Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`), CORS vypnuto výchozím, startup diagnostics (dev mode → exit 1), Docker non-root user | `.env.production.example` neúplný (14 vs. 46 vars); `/metrics` bez tokenu výchozím |
| **A06** | Vulnerable and Outdated Components | 🟡 **Částečné** | `pip-audit --strict --desc` v CI na každém PR, TruffleHog secret scanning | Chybí SAST (Semgrep/Bandit), SBOM, runtime SCA |
| **A07** | Identification and Authentication Failures | ✅ **Splněno** | `hmac.compare_digest()`, per-IP + per-key rate limiting, key revokace s cache eviction, expiry kontrola (`expires_at`), LRU cache s GC | Rate limiting jen in-memory (single-process) |
| **A08** | Software and Data Integrity Failures | 🟡 **Částečné** | GitHub Actions CI, Docker build pipeline, dependency lock files | Chybí artifact signing (cosign/Sigstore), SBOM |
| **A09** | Security Logging and Monitoring Failures | ✅ **Splněno** | Duální audit log (JSON přes `engramia.audit` logger + PostgreSQL `audit_log` tabulka), strukturované events (AUTH_FAILURE, RATE_LIMITED, KEY_*, DATA_EXPORTED…), Loki forwarding, Alertmanager | Retence jen 90 dní → zvýšit na 2+ roky pro enterprise |
| **A10** | Server-Side Request Forgery | ⚠️ **Riziko** | — | **Žádné explicitní SSRF kontroly pro webhook URL nebo LLM provider URL** |

**Výsledek: 6/10 plně splněno, 3/10 částečné, 1/10 riziko**

---

## 5. OWASP API Security Top 10 — Per-Item Status

| # | Kategorie | Status | Evidence | Mezera |
|---|-----------|--------|----------|--------|
| **API1** | Broken Object Level Authorization | ✅ **Splněno** | Tenant izolace via contextvars, project-scoped DB queries, všechny endpointy vyžadují auth | Ověřit všechny list endpoints pro tenant leakage |
| **API2** | Broken Authentication | ✅ **Splněno** | Timing-safe porovnání, multi-mode auth, žádná JWT algorithm confusion (explicit HS256/RS256), bootstrap token timing-safe | — |
| **API3** | Broken Object Property Level Authorization | 🟡 **Částečné** | Pydantic response schemas vylučují citlivá pole; key hash se nevrací v list | Ověřit konzistenci response schemas přes všechny endpointy |
| **API4** | Unrestricted Resource Consumption | 🟡 **Částečné** | Rate limiting (60 req/min default, 10 req/min LLM) + body size limit (1 MB) + LLM response truncation (20K) + quota enforcement | In-memory rate limiter — nedistribuovatelný, single-process only |
| **API5** | Broken Function Level Authorization | ✅ **Splněno** | Každý route handler má `require_auth` + `require_permission()` dependency — ověřeno v `routes.py` | — |
| **API6** | Unrestricted Access to Sensitive Business Flows | 🟡 **Částečné** | Billing quota enforcement, Stripe checkout session | Žádná bot protection na checkout flow |
| **API7** | Server Side Request Forgery | ❌ **Nesplněno** | — | **Chybí URL allowlist / SSRF filtr pro webhook endpointy** |
| **API8** | Security Misconfiguration | ✅ **Splněno** | Security headers, CORS politika, startup diagnostics, OpenAPI expozice záměrná | `/metrics` endpoint — doporučit vynutit token |
| **API9** | Improper Inventory Management | 🟡 **Částečné** | OpenAPI docs (`/docs`, `/redoc`), verzovaná API (`/v1/`) | Žádný staging/shadow API registry |
| **API10** | Unsafe Consumption of APIs | 🟡 **Částečné** | LLM response truncation, Pydantic validace provider responses | Timeout enforcement na LLM volání není dokumentován |

**Výsledek: 4/10 plně splněno, 5/10 částečné, 1/10 nesplněno**

---

## 6. ISO 27001:2022 — Top 20 Nejdůležitějších Kontrol

| Control ID | Oblast | Status | Evidence | Gap / Doporučená akce |
|-----------|--------|--------|----------|----------------------|
| **A.5.1** | Bezpečnostní politiky | ✅ | `SECURITY.md`, `docs/production-hardening.md` | — |
| **A.5.2** | Role a odpovědnosti IS | ❌ | — | Definovat CISO/security owner roli |
| **A.5.9** | Inventář aktiv | ⚠️ | Docker services, `dependency-licenses.json` | Chybí formální cloud asset register |
| **A.5.10** | Acceptable use policy | ❌ | — | Vytvořit AUP pro zaměstnance/contractors |
| **A.5.15** | Řízení přístupu | ✅ | RBAC v `permissions.py`, multi-mode auth | — |
| **A.5.16** | Správa identit | ✅ | API klíče + OIDC, lifecycle management (`keys.py`) | — |
| **A.5.17** | Autentizační informace | ✅ | Timing-safe, SHA-256, key rotation endpoint, expiry kontrola | OIDC JWKS cache TTL 60s (nízké riziko) |
| **A.5.23** | Bezpečnost cloud services | ⚠️ | Sub-procesory zdokumentováni v `data-handling.md` | Transfer mechanismy pro US sub-procesory chybí v PP/DPA |
| **A.5.24** | Plánování incident managementu | ❌ | Runbooks existují | **Formální IRP s definovanými kroky chybí** |
| **A.5.25** | Hodnocení incidentů | ❌ | — | Definovat severity klasifikaci (P0 = systém down, P1 = data breach…) |
| **A.5.26** | Reakce na incidenty | ⚠️ | 12 runbooks pokrývá operační scénáře | Chybí security incident workflow |
| **A.5.27** | Poučení z incidentů | ❌ | — | Lessons-learned proces po každém P0/P1 |
| **A.5.30** | Business continuity | ✅ | DR plán s RTO 4h, RPO 24h v `docs/disaster-recovery.md` | Backup není automatizován |
| **A.5.33** | Ochrana záznamů | ✅ | Audit log s retention politikou, Loki forwarding | 90 dní → zvýšit na 2 roky |
| **A.5.34** | Soukromí a ochrana dat | ✅ | GDPR tooling, DSR, PII redakce | Viz GDPR sekce |
| **A.8.2** | Privilegovaný přístup | ✅ | Non-root Docker user, SSH deploy key only | — |
| **A.8.8** | Řízení technických zranitelností | 🟡 | `pip-audit --strict` v CI | Chybí pravidelný penetrační test, runtime SCA |
| **A.8.12** | Prevence úniku dat | ✅ | PII redakce pipeline výchozí zapnuta (`ENGRAMIA_REDACTION=true`) | — |
| **A.8.15** | Logování | ✅ | Strukturovaný JSON + DB audit log, Loki | Retence 90 dní |
| **A.8.16** | Monitoring | ✅ | Prometheus + Grafana + Alertmanager + Loki + Uptime Kuma | — |
| **A.8.25** | Secure development lifecycle | ✅ | Pre-commit hooks, CI/CD, opakované audit cykly | SAST chybí |
| **A.8.29** | Security testing | 🟡 | Unit testy 80.29% coverage, pip-audit | Chybí SAST, penetrační test |
| **A.8.32** | Change management | ✅ | Git PRs, CI checks, CHANGELOG, lineární DB migrace | — |

**Splněno: ~14/23 klíčových kontrol plně (61 %), 4/23 částečně → efektivně ~66 %**

---

## 7. CIS Controls v8

### Implementation Group 1 — Tier 1 (Essential)

| CIS | Popis | Status | Evidence |
|-----|-------|--------|----------|
| 1.1 | Inventář enterprise aktiv | ⚠️ | Docker services popsány v compose; chybí cloud asset register |
| 2.1 | Inventář software aktiv | ✅ | `pyproject.toml`, `dependency-licenses.json` (23 KB) |
| 3.1 | Data management proces | ✅ | `docs/data-handling.md`, `governance/lifecycle.py` |
| 3.2 | Datový inventář | ✅ | Data model a klasifikace zdokumentovány |
| 4.1 | Secure configuration proces | ✅ | `.env.example`, `docs/production-hardening.md` |
| 5.1 | Inventář účtů | ⚠️ | API klíče v DB; cloud IAM inventory chybí |
| 5.2 | Unikátní přihlašovací údaje | ✅ | Random 43-char base64url klíče, žádná sdílená hesla |
| 6.1 | Proces přidělení přístupu | ✅ | Bootstrap + key provisioning + RBAC workflow |
| 6.2 | Proces odebrání přístupu | ✅ | Key revokace + okamžitá LRU cache eviction |
| 7.1 | Vulnerability management | ✅ | `pip-audit --strict --desc` v každém PR |
| 8.1 | Audit log proces | ✅ | Duální audit trail (JSON + PostgreSQL) |
| 10.1 | Kapacita pro obnovu dat | ✅ | Backup skripty + DR runbook |
| 11.1 | Síťový firewall | ✅ | Docker network izolace, pouze Caddy exposed na 80/443 |
| 12.1 | Network infrastructure management | ✅ | `docker-compose.prod.yml` — API internal only (127.0.0.1:8000) |
| 13.1 | Network monitoring | ✅ | Prometheus + Grafana + Loki |

**IG1 Score: 13/15 (87 %)**

### Implementation Group 2 — Tier 2 (Foundational)

| CIS | Popis | Status | Mezera / Doporučení |
|-----|-------|--------|---------------------|
| 2.3 | Kontrola neautorizovaného software | ❌ | Žádný software allowlist |
| 3.3 | Data ACLs | ✅ | RBAC per project/tenant |
| 3.6 | Šifrování dat v klidu | ❌ | Operátorova zodpovědnost — zdokumentovat jako povinný requirement |
| 3.11 | Šifrování dat v přenosu | ✅ | TLS via Caddy (Let's Encrypt), HSTS |
| 4.2 | Secure config pro síťovou infrastrukturu | ✅ | Caddy config, Docker networking |
| 5.3 | Deaktivace dormantních účtů | ⚠️ | Key expiry existuje; žádný auto-disable po N dnech inaktivity |
| 6.3 | MFA pro externí přístup | ❌ | Žádné MFA; jen API key nebo OIDC (bez vynucení MFA) |
| 7.3 | Automatizované vulnerability scany | 🟡 | pip-audit jen; chybí SAST (Semgrep/Bandit) |
| 7.5 | Penetrační testování | ❌ | Neprovedeno |
| 8.2 | Sběr audit logů | ✅ | Dual log + Loki forwarding |
| 8.7 | Alerting na anomálie v audit logu | ⚠️ | Alertmanager nastaven; custom detection pravidla nejsou zdokumentována |
| 9.2 | DNS filtering | ❌ | Žádný DNS filtering |
| 10.2 | Ochrana recovery dat | ⚠️ | Šifrování záloh není explicitně zdokumentováno |
| 11.2 | Remote access management | ✅ | SSH deploy key only, žádné přímé root přihlášení |
| 16.1 | Application security program | 🟡 | Neformální; audit cykly existují; žádný AppSec program charter |

**IG2 Score: 7/15 (47 %)**

---

## 8. PCI DSS — Scope Reduction přes Stripe

### Analýza Scope

**Platební model:** Stripe-hosted Checkout → **SAQ A eligible** (nejnižší možný PCI scope)

```
Zákazník → Stripe Checkout Page → Stripe zpracovává kartu → Stripe webhook → Engramia
                                        ↑
                              Karta se nikdy nedostane sem
```

Žádná data platební karty (PAN, CVV, expiry) nikdy neprojdou přes Engramia servery.

### Verifikace SAQ A Předpokladů

| Kritérium SAQ A | Status | Evidence |
|-----------------|--------|----------|
| Karta neprojde Engramia serverem | ✅ | Stripe Checkout / Payment Links (STRIPE.md) |
| Stripe webhook podpis ověřen | ✅ | `stripe.Webhook.construct_event()` v `billing/webhooks.py` |
| Stripe secret key mimo kód | ✅ | Env var `STRIPE_SECRET_KEY`, v `.gitignore`, nikdy commitnut |
| Idempotence webhook událostí | ✅ | `processed_webhook_events` tabulka — double-processing prevence |
| TLS pro veškerou komunikaci | ✅ | Caddy + Let's Encrypt, HSTS |
| Žádné ukládání PAN/CVV | ✅ | Engramia nikdy nevidí kartu ani CVV |
| Metering je atomický | ✅ | `INSERT ... ON CONFLICT DO UPDATE` v `billing/metering.py` |

### PCI DSS SAQ A Požadavky

| Req | Popis | Status | Gap |
|-----|-------|--------|-----|
| 2.2 | Secure system configs | ✅ | — |
| 6.2 | Ochrana platební stránky | ✅ N/A | Stripe-hosted |
| 6.3 | Identifikace zranitelností | 🟡 | pip-audit; chybí SAST |
| 8.2 | Unikátní uživatelská ID | ✅ | API klíče + RBAC |
| 8.3 | Silná autentizace | ✅ | — |
| 12.1 | Security politika | ✅ | SECURITY.md |
| 12.3 | Risk assessment | ✅ | Audit cykly |
| 12.6 | Security awareness training | ❌ | Žádný dokumentovaný program |
| 12.10 | Incident response plan | ❌ | **Formální IRP chybí** |

**PCI DSS Score (SAQ A): 85 %**
**Scope je správně minimalizován.** Zbývají 2 administrative gaps: awareness training + IRP.

---

## 9. Findings Tabulka

| # | Finding | Standard(y) | Severity | Effort | Doporučení |
|---|---------|-------------|----------|--------|------------|
| **F1** | Chybí Records of Processing Activities (RoPA) | GDPR Art. 30 | 🔴 High | Low | Vytvořit tabulku se všemi aktivitami zpracování (účel, kategorie, příjemci, retence) |
| **F2** | Chybí Data Protection Impact Assessment (DPIA) | GDPR Art. 35 | 🔴 High | Medium | Provést DPIA pro AI zpracování osobních dat — standard template je dostupný |
| **F3** | Žádný formální Incident Response Plan s 72h notifikací | GDPR Art. 33, PCI 12.10, SOC2 CC7.3, ISO A.5.24 | 🔴 High | Low | Napsat IRP: detekce → severity → izolace → notifikace ÚOOÚ do 72h → komunikace zákazníkům |
| **F4** | Transfer mechanismy pro US sub-procesory nedokumentovány | GDPR Art. 46 | 🔴 High | Low | Přidat SCCs reference pro OpenAI, Anthropic, Stripe do Privacy Policy a DPA |
| **F5** | In-memory rate limiting — nedistribuovatelný při multi-process deployment | OWASP API4, SOC2 CC6 | 🔴 High | Medium | Implementovat Redis-backed rate limiter; existující in-memory kód zachovat jako fallback |
| **F6** | Šifrování dat v klidu chybí v aplikační vrstvě | CIS 3.6, ISO A.8.24, SOC2 C1, OWASP A02 | 🔴 High | Medium | Zdokumentovat jako povinný operátorský requirement; doporučit PostgreSQL pgcrypto nebo filesystem encryption na Hetzner |
| **F7** | Backup není automatizován | SOC2 A1.4, CIS 10.1 | 🟡 Medium | Low | Cron job pro `pg_dump` + upload do bezpečného storage + alerting při selhání |
| **F8** | Chybí SAST/DAST v CI pipeline | OWASP A06, CIS 7.3, ISO A.8.29 | 🟡 Medium | Low | Přidat Semgrep nebo Bandit do `ci.yml`; začít non-blocking, pak enforcing |
| **F9** | Žádný Software Bill of Materials (SBOM) | CIS 2.1, OWASP A06, ISO A.5.9 | 🟡 Medium | Low | CycloneDX nebo Syft v `docker.yml` → artifact upload ke každému release |
| **F10** | Žádné artifact signing pro Docker images | OWASP A08, ISO A.8.25 | 🟡 Medium | Low | cosign/Sigstore v `docker.yml`; supply chain security |
| **F11** | `.env.production.example` neúplný (14 vs. 46 proměnných) | SOC2 CC5, CIS 4.1 | 🟡 Medium | Low | Zdokumentovat všech 46 production env vars s popisem a default hodnotami |
| **F12** | Žádné MFA pro admin operace | CIS 6.3, ISO A.5.17, SOC2 CC6 | 🟡 Medium | Medium | OIDC s MFA enforcement pro admin a owner roli; nebo hardware key |
| **F13** | Žádný penetrační test | CIS 7.5, ISO A.8.8 | 🟡 Medium | High | Roční third-party pen test; povinný před SOC 2 audit |
| **F14** | Docker resource limits nejsou nastaveny | SOC2 A1.1, CIS 4.1 | 🟡 Medium | Low | Přidat `deploy.resources.limits` (CPU, memory) do `docker-compose.prod.yml` |
| **F15** | Právní dokumenty bez právní revize | GDPR, BSL 1.1 | 🟡 Medium | Medium | Attorney review ToS, Privacy Policy, DPA šablona, Commercial License |
| **F16** | SSRF kontroly chybí pro webhook/LLM URL | OWASP API7, OWASP A10 | 🟡 Medium | Low | URL allowlist + SSRF filtr pro webhook endpointy; validace provider URL |
| **F17** | Formální asset register chybí | CIS 1.1, ISO A.5.9 | 🟢 Low | Low | Vytvořit cloud asset inventory (spreadsheet: server, domény, DNS, certifikáty) |
| **F18** | Prometheus `/metrics` bez tokenu výchozím | OWASP A05, SOC2 CC6 | 🟢 Low | Low | Přidat `ENGRAMIA_METRICS_TOKEN=required` jako doporučení do production-hardening.md |
| **F19** | Audit log retence jen 90 dní | SOC2 CC7, ISO A.8.15 | 🟢 Low | Low | Zvýšit na 2 roky nebo exportovat do SIEM (Loki long-term storage) |
| **F20** | DPO posouzení nezdokumentováno | GDPR Art. 37 | 🟢 Low | Low | Zdokumentovat proč DPO není povinný (velikost firmy, povaha zpracování) |
| **F21** | Security awareness training chybí v dokumentaci | PCI DSS 12.6, ISO A.6.3, SOC2 CC1.4 | 🟢 Low | Low | Zdokumentovat neformální security onboarding checklist |
| **F22** | DSR záznamy nemají definovanou retenci | GDPR, SOC2 P5 | 🟢 Low | Low | Přidat retenci DSR záznamů (doporučeno 5 let) do `governance/lifecycle.py` |
| **F23** | Art. 18/21 práva subjektů nejsou implementována | GDPR Art. 18, 21 | 🟢 Low | Low | Přidat DSR typ `restriction`; zdokumentovat scope Art. 21 (neaplikuje se pro čistě smluvní zpracování) |

---

## 10. Remediation Roadmap

### Fáze 1 — Ihned (Před Veřejným Spuštěním)

**Cíl:** Eliminovat kritická právní a bezpečnostní rizika. Odhadovaný effort: **3–5 pracovních dní.**

| Priority | Finding | Konkrétní akce | Effort |
|----------|---------|----------------|--------|
| P0 | F3 — IRP | Napsat 2-3 stránkový Incident Response Plan s 72h notifikační procedurou pro ÚOOÚ | 1 den |
| P0 | F1 — RoPA | Vytvořit tabulku Records of Processing Activities | 4 hod |
| P0 | F4 — SCCs | Přidat sekci "International Transfers" s SCCs referencemi do Privacy Policy a DPA | 2 hod |
| P0 | F11 — .env | Doplnit `.env.production.example` se všemi 46 production proměnnými | 4 hod |
| P1 | F14 — Docker limits | Přidat CPU/memory resource limits do `docker-compose.prod.yml` | 1 hod |
| P1 | F7 — Backup | Cron job pro automatické zálohy + alerting při selhání | 1 den |
| P1 | F8 — SAST | Přidat Semgrep nebo Bandit do `ci.yml` (začít non-blocking) | 2 hod |
| P1 | F16 — SSRF | URL validace/allowlist pro webhook endpointy | 4 hod |
| P2 | F18 — Metrics auth | Dokumentovat `ENGRAMIA_METRICS_TOKEN` jako required v production-hardening | 30 min |

### Fáze 2 — Před Prvním Enterprise Zákazníkem

**Cíl:** Splnit enterprise procurement questionnaire, umožnit podpis DPA. Odhadovaný effort: **2–3 týdny (včetně externího).**

| Priority | Finding | Konkrétní akce | Effort |
|----------|---------|----------------|--------|
| P0 | F15 — Legal review | Attorney review ToS, Privacy Policy, DPA šablona, Commercial License | 2 týdny ext. |
| P0 | F6 — At-rest encryption | Zprovoznit disk/DB encryption na Hetzner + zdokumentovat jako povinný requirement | 2 dny |
| P1 | F5 — Redis rate limit | Implementovat Redis-backed rate limiter pro multi-process deployment | 3 dny |
| P1 | F2 — DPIA | Provést Data Protection Impact Assessment pro AI zpracování | 2 dny |
| P2 | F9 — SBOM | CycloneDX generování v CI + artifact upload ke každému release | 4 hod |
| P2 | F10 — Artifact signing | cosign v `docker.yml` | 1 den |
| P2 | F19 — Log retention | Prodloužit audit log retenci na 2 roky nebo SIEM export | 1 den |
| P2 | F22 — DSR retention | Přidat retenci DSR záznamů do `governance/lifecycle.py` | 2 hod |
| P3 | F20 — DPO | Zdokumentovat posouzení DPO povinnosti | 2 hod |
| P3 | F21 — Training | Napsat security awareness onboarding checklist | 2 hod |

### Fáze 3 — Před SOC 2 Audit

**Cíl:** Formální audit readiness. Odhadovaný effort: **1–2 měsíce.**

| Finding | Konkrétní akce | Effort |
|---------|----------------|--------|
| F12 — MFA | OIDC s MFA enforcement pro admin/owner role | 5 dní |
| F13 — Pen test | Third-party penetrační test | 1–2 týdny ext. |
| F17 — Asset register | Formální cloud asset inventory | 1 den |
| — | Formální ISMS framework (ISO 27001 compliant) | 4–6 týdnů |
| — | Segregation of Duties politika | 1 den |
| — | Vendor risk management proces | 1 týden |
| — | Continuous compliance monitoring (Vanta, Drata nebo DIY) | 2–4 týdny |
| — | Risk register s formálními vlastníky | 1 den |
| — | Annual security review procedure | 1 den |

---

## 11. "Compliant Without Certification" Checklist

> Co musíme mít, aby zákazník mohl říct: **"Ano, používáme bezpečného a GDPR-compliant dodavatele."**

### A. Technická Bezpečnost

- [x] TLS šifrování veškeré komunikace (Let's Encrypt via Caddy, HSTS)
- [x] Autentizace vyžadována na všech API endpointech
- [x] Role-based access control s least privilege (4 role, striktní hierarchie)
- [x] Multi-tenancy s přísnou izolací (contextvars + DB scope)
- [x] Audit trail — kdo, co, kdy (JSON + PostgreSQL, Loki)
- [x] Bezpečnostní HTTP hlavičky (X-Content-Type-Options, X-Frame-Options, Referrer-Policy)
- [x] Input validace + SQL injection prevence (Pydantic + SQLAlchemy parameterized)
- [x] Rate limiting + body size limity (1 MB default)
- [x] Timing-safe token porovnání (`hmac.compare_digest`)
- [x] SHA-256 hashing klíčů — nikdy plain text v DB
- [x] Docker non-root user, network izolace
- [x] Stripe-hosted platby — žádná karta neprochází serverem
- [ ] Šifrování dat v klidu ← F6 (Fáze 2)
- [ ] Redis rate limiting pro distribuované deployment ← F5 (Fáze 2)
- [ ] SSRF ochrana pro webhook URL ← F16 (Fáze 1)

### B. GDPR / Ochrana Dat

- [x] Právo na výmaz implementováno (Art. 17) — kaskádové mazání
- [x] Právo na přenositelnost dat (Art. 20) — NDJSON export
- [x] DSR tracking s 30denní SLA (Art. 15-20)
- [x] PII redakce pipeline výchozí zapnuta
- [x] Datová klasifikace zdokumentována (PUBLIC/INTERNAL/CONFIDENTIAL)
- [x] Sub-procesor seznam publikován
- [x] Privacy Policy a Cookie Policy publikovány
- [x] DPA šablona připravena pro zákazníky
- [x] Retention politiky implementovány v kódu
- [ ] Records of Processing Activities (RoPA) ← F1 (Fáze 1)
- [ ] DPIA ← F2 (Fáze 2)
- [ ] IRP s 72h notifikační SLA ← F3 (Fáze 1)
- [ ] SCCs pro US sub-procesory zdokumentovány ← F4 (Fáze 1)
- [ ] Attorney-reviewed DPA + Privacy Policy + ToS ← F15 (Fáze 2)

### C. DevSecOps

- [x] CI/CD s automatickým security scanningem (pip-audit + TruffleHog)
- [x] 80 %+ test coverage s vynuceným threshold
- [x] Pre-commit hooks
- [x] Závislosti verzovány (lock files, `pyproject.toml`)
- [x] Lineární migrace chain bez větví (001→012)
- [x] Health checks na všech Docker services
- [ ] SAST v CI (Semgrep/Bandit) ← F8 (Fáze 1)
- [ ] SBOM generování ← F9 (Fáze 2)
- [ ] Artifact signing ← F10 (Fáze 2)

### D. Operational Readiness

- [x] Monitoring stack (Prometheus + Grafana + Loki + Alertmanager + Uptime Kuma)
- [x] Disaster Recovery plán (RTO 4h, RPO 24h)
- [x] 12 operačních runbooks
- [x] Backup skripty existují
- [ ] Automatizované zálohy ← F7 (Fáze 1)
- [ ] Formální Incident Response Plan ← F3 (Fáze 1)
- [ ] Docker resource limits ← F14 (Fáze 1)

### Celkové Skóre Checklist

| Fáze | Splněno | Celkem | % |
|------|---------|--------|---|
| **Aktuální stav (2026-04-05)** | **25** | **38** | **66 %** |
| Po Fázi 1 (∼5 dní práce) | 33 | 38 | 87 % |
| Po Fázi 2 (∼3 týdny) | **38** | **38** | **100 %** |

---

## Appendix: Verifikované Silné Stránky

> Důkazy pro enterprise procurement questionnaire.

### Autentizace & Autorizace

| Kontrola | Kód | Detail |
|----------|-----|--------|
| Timing-safe token porovnání | `api/auth.py:_env_auth()` | `hmac.compare_digest()` — odolné proti timing attacks |
| SHA-256 hashing klíčů | `api/auth.py:_hash_key()` | Nikdy plain text v DB |
| LRU cache s GC | `api/auth.py:_lookup_key_cached()` | Max 4096 entries, TTL 60s, GC každých 5 min |
| Race condition prevence | `api/keys.py` | PostgreSQL advisory locks (`pg_advisory_xact_lock`) |
| RBAC hierarchie | `api/permissions.py` | `reader ⊂ editor ⊂ admin ⊂ owner`, striktní superset |
| Bootstrap ochrana | `api/keys.py` | Timing-safe `hmac.compare_digest()` + one-time advisory lock |

### Data Izolace

| Kontrola | Kód | Detail |
|----------|-----|--------|
| Tenant izolace | `_context.py` | Python contextvars pro async safe izolaci |
| Project-scoped queries | `api/routes.py` | Všechny DB queries scope na `project_id`/`tenant_id` |
| Separátní auth engine | `api/app.py:_make_auth_engine()` | Vlastní SQLAlchemy engine pro api_keys lookup |

### Billing Security

| Kontrola | Kód | Detail |
|----------|-----|--------|
| Webhook signature verification | `billing/webhooks.py` | `stripe.Webhook.construct_event()` |
| Idempotence | `billing/service.py` | `processed_webhook_events` tabulka |
| Atomické metering | `billing/metering.py` | `INSERT ... ON CONFLICT DO UPDATE` — bez race conditions |
| Grace period | `billing/models.py` | 7 dní po past_due, připomínka v den 5 |

### GDPR Tooling

| Kontrola | Kód | Detail |
|----------|-----|--------|
| Kaskádové mazání | `governance/deletion.py` | storage → jobs → keys (revokace) → audit (scrub) → projects |
| DSR tracking | `governance/dsr.py` | Status, SLA, overdue detection, 4 typy requests |
| PII redakce | `governance/redaction.py` | Pipeline výchozí zapnuta (`ENGRAMIA_REDACTION=true`) |
| Portabilní export | `governance/export.py` | NDJSON formát (Art. 20) |

### CI/CD Security

| Kontrola | Soubor | Detail |
|----------|--------|--------|
| Dependency audit | `.github/workflows/ci.yml` | `pip-audit --strict --desc` na každém PR |
| Secret scanning | `.github/workflows/ci.yml` | `trufflesecurity/trufflehog@v3.88.17 --only-verified` |
| Coverage enforcement | `.github/workflows/ci.yml` | `fail_under=80` — nelze mergovat bez 80 % coverage |
| Version consistency | `.github/workflows/docker.yml` | Post-deploy smoke test ověří verzi |

---

*Report generován: 2026-04-05 | Základ: agent-brain v0.6.5 | Metoda: statická analýza zdrojového kódu + dokumentace*
*Příští doporučený review: před prvním enterprise zákazníkem nebo po Fázi 1 remediaci*
