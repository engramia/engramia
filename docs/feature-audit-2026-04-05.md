# Engramia — Feature Audit 2026-04-05

**Rozsah:** Hluboká analýza produktového offeringu v kontextu konkurence a trhu.
**Cíl:** Zjistit launch-readiness, silné/slabé stránky, a konkrétní feature priority.
**Verze:** v0.6.5 | Datum: 2026-04-05

---

## A) Positioning Assessment

### Kde Engramia sedí na mapě

Engramia zaujímá **unikátní průsečík tří kategorií**, které jsou typicky oddělené produkty:

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   Agent Memory      Agent Eval       Agent Observability    │
│   (Mem0, Zep,       (LangSmith,      (LangFuse, Helicone,   │
│    LangMem)          Braintrust,      Phoenix Arize,        │
│                      DeepEval)        W&B Weave)            │
│                                                             │
│              ┌─────────────────┐                            │
│              │    ENGRAMIA     │                            │
│              │  Execution mem  │                            │
│              │  + Eval layer   │                            │
│              │  + ROI analytics│                            │
│              └─────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

**Klíčové pozicování:** Engramia je **reusable execution memory** — ne konverzační paměť (Mem0, Zep), ne pure-play eval platform (LangSmith, Braintrust), ale paměť **co fungovalo** v kontextu kódu agentů. Tato niche je skutečně prázdná.

### Unique Differentiators vs. Competitors

| Differentiator | Engramia | Mem0 | Zep | LangSmith | Braintrust | LangFuse |
|---|---|---|---|---|---|---|
| Execution pattern memory (kód, ne chat) | ✅ **Jediný** | ❌ | ❌ | ❌ | ❌ | ❌ |
| Eval-weighted recall (lepší pattern → vyšší priorita) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Closed-loop (learn → eval → recall → improve) | ✅ | ❌ | ❌ | partial | ❌ | ❌ |
| Multi-evaluator s variance detection | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Time-decay aging (paměť zastarává) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Framework-agnostic (Python + REST + MCP) | ✅ | partial | partial | ❌ (LangChain-first) | partial | ✅ |
| Self-hosted + cloud | ✅ | partial | ✅ | partial | ❌ | ✅ |
| Adversarial detection (hardcoded outputs) | ✅ **Jediný** | ❌ | ❌ | ❌ | ❌ | ❌ |
| Prompt evolution z eval feedbacku | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| GDPR-native (retention, export, redaction) | ✅ | ❌ | ❌ | partial | ❌ | ✅ |
| RBAC s 4 rolemi | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| MCP server (Claude Desktop, Cursor) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| ROI analytics (composite score) | ✅ | ❌ | ❌ | partial | partial | partial |

**Benchmark validace:** 93% task success rate na 254 reálných runech (Agent Factory V2) — toto je vzácný příklad produktu s vlastní validací v produkci.

### Kde je Engramia slabší

1. **Konverzační memory chybí** — pro chatboty nebo RAG pipeline je Mem0/Zep přirozenější volba. Engramia řeší execution memory, ne chat history.
2. **Žádný visual trace explorer** — LangSmith/LangFuse mají krásné trace waterfall views. Engramia má jen Prometheus/Grafana metriky, ne per-request trace UI.
3. **Žádné dataset management** — kompetice umožňuje nahrát eval dataset (CSV/JSON) a pouštět regresní testy. Engramia toto nemá.
4. **Žádná community** — Mem0, LangFuse, DeepEval mají aktivní Discord. Engramia nemá žádný veřejný community channel.
5. **JavaScript/TypeScript SDK chybí** — konkurence má JS SDKs. Engramia je Python-only library; REST API funguje z JS, ale není idiomatic SDK.
6. **Omezená škálovatelnost** — JSON storage pro >100k patterns není vhodná. pgvector scales do ~1M, ale dedicated vector DB (Qdrant/Milvus/Weaviate) chybí.
7. **Žádné dataset/benchmark sdílení** — competitors (zejm. Braintrust) umožňují sdílet eval datasets mezi týmy. Engramia patterns jsou private per-project.

---

## B) Product Manager Pohled

### Je core value proposition jasná?

**Partially.**

Hlavička README: *"Reusable execution memory and evaluation infrastructure for AI agent frameworks"* — technicky přesné, ale nenabízí okamžité "aha".

Silnější framing by byl: **"Your agents don't learn from what worked — Engramia fixes that."** ✅ (Toto je v README jako vedlejší sentence, ale mělo by být headline.)

Claim "93% task success rate" a "+93 pp vs cold start (5.5% → 98.8%)" je silný a validovaný benchmarkem. Toto je **killer stat** pro marketing, ale je pohřben v roadmap. Měl by být na landing page héro sekci.

### Chybí table-stakes features (co zákazníci očekávají jako samozřejmost)

| Feature | Status | Proč table-stakes |
|---|---|---|
| Cloud signup flow (email + password / OAuth) | ❌ BLOCKING | Každý SaaS to musí mít |
| Public status page | ❌ chybí | Zákazníci si to první hledají při výpadku |
| Support email / ticketing | ❌ chybí | Pro paying customers ($29+) je to minimum |
| JavaScript/TypeScript SDK | ❌ chybí | Polovina AI dev světa je JS-first |
| Webhook notifications (Slack/Discord) | ❌ v roadmap Phase 6 | CI/CD integrace bez notifikací je incomplete |
| Eval dataset management (upload, version) | ❌ chybí | Braintrust/LangSmith baseline |
| Trace/run detail view v dashboard | ❌ partial | Admin dashboard má metriky, ne per-run detail |
| GitHub Actions integration | ❌ chybí | Developer workflow je nyní CI-first |

### Quick wins (nízká effort, vysoký impact)

1. **Public status page** (Uptime Kuma je deploynutá, jen chybí public URL za Caddyfile entry) — 1 hodina work
2. **OG tags / Twitter cards** na website — 2 hodiny, obrovský impact na social sharing
3. **robots.txt + sitemap** — 1 hodina
4. **Support email + GitHub Discussions** — 0 code, jen konfigurace
5. **"93% success rate" hero stat na landing page** — copy change, 30 minut
6. **Slack/Discord community link** — 0 code, community setup
7. **Webhook example pro Slack notification** — 1 den code, ukázkový use case

### Missing "aha moment" features

**Aha moment** pro Engramia by měl nastat v moment kdy agent poprvé:
1. Zavolá `recall()` a dostane zpět přesné řešení které použil 3 týdny ago
2. Vidí jak `eval_score` postupně roste across runs
3. Dostane `get_feedback()` a zjistí systémové problémy v jeho agentech

Problém: **cloud onboarding flow neexistuje** — zákazník nikdy k tomuto "aha" momentu nedojde. To je fundamentální blocker.

**Missing: Demo mode / interactive playground** — Braintrust a LangSmith mají demo datasets a pre-seeded examples. Zákazník si může vyzkoušet UI bez setup. Engramia nemá žádný takový quickstart.

---

## C) CTO / Technical Pohled

### Enterprise Readiness Assessment

| Requirement | Status | Detail |
|---|---|---|
| SSO / OIDC | ✅ Stable | Okta, Azure AD, Auth0, Keycloak; RS/ES/PS algos; allowlist |
| RBAC | ✅ Stable | 4 role: owner/admin/editor/reader; hierarchy enforcement |
| Audit log | ✅ Stable | Structured JSON, auth_failure, pattern events, data events |
| Multi-tenancy | ✅ Stable | Scope isolation via contextvars + DB UNIQUE constraint |
| Data residency / self-hosted | ✅ Stable | Docker Compose + K8s manifests; air-gapped capable |
| GDPR compliance | ✅ Stable | PII redaction, retention, export (Art. 20), delete (Art. 17), DSR |
| Encryption at transit | ✅ Stable | Caddy auto-TLS (Let's Encrypt) |
| Encryption at rest | ⚠️ GAP | PostgreSQL tablespace encryption: závisí na infra, není dokumentována. Audit finding v Privacy Policy §7. |
| SOC 2 Type II | ⚠️ Partial | SOC 2 control mapping dokument existuje, ale formální audit nebyl proveden |
| WAF | ❌ chybí | Caddy nemá mainstream WAF plugin; in-app rate limiting je single-process |
| External secrets management | ❌ roadmap | Vault/AWS Secrets Manager/Azure Key Vault plánováno Phase Enterprise |
| mTLS | ❌ roadmap | Zero-trust service-to-service auth plánováno |
| SAML SSO | ❌ roadmap | Jen OIDC; SAML je common enterprise requirement |
| DLP/egress control | ❌ chybí | Žádná kontrola nad tím, co LLM provider vidí |
| Compliance: HIPAA/SOC2/ISO27001 | ❌ chybí | Tyto certifikace nejsou ani roadmapované |

### Integrations Missing (must-have vs. nice-to-have)

**Must-have před enterprise sales:**
- **OpenAI Agents SDK adapter** — OpenAI Agents SDK (2025) je mainstream; chybí native integration
- **JavaScript/TypeScript SDK** — velký podíl enterprise developerů
- **SAML SSO** — Okta + Azure AD enterprise deployments
- **SOC 2 Type II certifikace** — enterprise procurement blocker

**Nice-to-have (significant competitive disadvantage bez nich):**
- Anthropic Agents SDK integration
- n8n / Zapier integration (automation studio segment)
- Dedicated vector DB (Qdrant/Milvus) pro 100k+ patterns
- GitHub integration (trigger eval run na PR)
- Voyage AI / Cohere embedding providers (Phase 8)

### Scalability / Performance Concerns

1. **In-memory rate limiter** — nepodporuje scale-out na >1 repliku. Dokumentováno jako known limitation. Blocker pro enterprise HA setup.
2. **JSON storage** — atomic file writes, thread-safe, ale ne vhodné pro produkci (žádný ACID, žádné concurrent readers ve scale). Dobré pro demo/dev only.
3. **pgvector limit** — ~1M vectors before degradation. Pro 100k+ patterns je nutný dedicated vector DB. Phase 8 roadmap.
4. **Async job queue** — DB-backed (PostgreSQL SKIP LOCKED) v prod mode — solidní. In-memory fallback v dev mode — jasně marked, OK.
5. **LLM concurrency** — bounded semaphore (default 10 concurrent), konfigurovatelné. OK pro MVP.

### Security/Compliance Gaps pro Enterprise

- Encryption at rest není explicitně řešena (závisí na hostingovém provideru)
- Security scanning v CI chybí (pip-audit, bandit, semgrep) — A06 OWASP gap
- PyPI environment protection je TODO (blocking pre-launch)
- K8s deployment používá plaintext secrets v YAML — potřebuje SealedSecrets/SOPS pro production K8s

---

## D) Developer Experience Pohled

### SDK Quality

| Aspekt | Hodnocení | Detail |
|---|---|---|
| Python API | ✅ Excellent | Čistá facade, Pydantic v2, type hints všude, Google docstrings |
| REST API | ✅ Excellent | FastAPI auto-Swagger, ReDoc, /docs endpoint |
| LangChain integration | ✅ Good | EngramiaCallback, auto_learn + auto_recall params |
| CrewAI integration | ✅ Good | EngramiaCrewCallback |
| CLI | ✅ Good | Typer + Rich, init/serve/status/recall/aging |
| MCP server | ✅ Forward-looking | Stdio transport, 7 tools, Claude Desktop/Cursor/Windsurf |
| Webhook SDK | ✅ Good | Stdlib-only client (no extra deps) |
| JavaScript SDK | ❌ chybí | REST API funguje, ale není idiomatic JS SDK |
| OpenAI Agents SDK | ❌ chybí | 2025 mainstream framework bez native integrace |
| Exception hierarchy | ✅ Good | EngramiaError → ProviderError/ValidationError/StorageError |

### Documentation Gaps

**Dobrý stav:**
- User guide 11 sekcí, kompletní
- API reference v MkDocs
- 12 runbooks
- REST API s curl příklady
- Security architecture, data handling, production hardening docs

**Gaps (z prelaunch auditu):**
- Stripe webhook setup pro self-hosted není v user-facing docs
- Key expiration parameter (`expires_at`) není dokumentován
- Audit log sekce chybí v user guide (jak číst, filtrovat, interpretovat)
- DSR workflow chybí v user guide
- Dunning visibility pro adminy není dokumentována
- Experimental features nemají explicitní "API may change" callout

### Onboarding Friction

**Self-hosted onboarding:** ✅ Solidní — 5 jasných kroků, docker compose up funguje.

**Cloud onboarding:** ❌ BLOCKING — zákazník nemá kde se zaregistrovat. Swagger UI jako "start" je technicky funkční, ale není user-friendly onboarding. Toto je P0 blocker.

**Time-to-first-value (self-hosted):** ~15-20 minut od `git clone` po první `recall()` s výsledkem. Akceptovatelné, ale lze zkrátit na <5 minut s interaktivním quickstart notebookem.

### Missing Developer-Friendly Features

| Feature | Competitors s tím | Priority |
|---|---|---|
| GitHub Actions action (`engramia/eval-action`) | LangSmith, Braintrust | P1 |
| Interactive Jupyter/Colab notebook quickstart | LangFuse, Mem0 | P1 |
| JavaScript/TypeScript SDK | Mem0, LangFuse, Braintrust | P1 |
| Testing sandbox (seed data, replay) | Braintrust, LangSmith | P1 |
| VS Code extension | LangSmith | P2 |
| OpenAPI generated client (multiple languages) | LangFuse | P2 |
| Real-time eval streaming (SSE/WebSocket) | LangSmith | P2 |
| Pattern search UI v dashboard | LangSmith traces view | P1 |
| Eval run comparison (before/after) | Braintrust | P1 |

---

## E) Go-to-Market Readiness

### Celkové hodnocení (1–10)

| Dimenze | Skóre | Zdůvodnění |
|---|---|---|
| **Core tech readiness** | 8/10 | Solidní základ, 726 testů, 80%+ coverage, 3 audit cykly |
| **Enterprise readiness** | 6/10 | RBAC/SSO/GDPR jsou, chybí SOC 2, SAML, WAF, secrets mgmt |
| **Developer experience** | 6/10 | Python SDK výborný, chybí JS SDK a GitHub Actions |
| **Product completeness** | 5/10 | Chybí cloud onboarding, dataset management, trace viewer |
| **Business readiness** | 4/10 | Legal review nevykonán, support channel chybí, emaily neověřeny |
| **Marketing/GTM** | 5/10 | Website připravena, OG tags chybí, community neexistuje |
| **Competitive positioning** | 8/10 | Genuinely unique niche, silný differentiator |

**Celkové GTM skóre: 6/10**

### Nejlepší ICP segmenty pro Launch MVP

#### ICP 1: Mid-size AI Platform Teams (BEST FIT)
- **Profil:** 10–100 devs, budují multi-agent pipelines na LangChain/CrewAI, mají opakované úlohy
- **Pain:** Agenti nepametají co fungovalo, opakují chyby, nelze měřit zlepšení
- **Engramia fit:** ⭐⭐⭐⭐⭐ — přesně pro ně
- **Willingness to pay:** $99–$499/mo
- **Where to find:** AI/ML LinkedIn groups, LangChain Discord, CrewAI community

#### ICP 2: Automation Studios & AI Dev Shops (GOOD FIT)
- **Profil:** Agentura budující AI řešení pro klienty, opakují podobné workflow automation úlohy
- **Pain:** Každý projekt začíná od nuly, nelze reuse co funguje u jiných klientů
- **Engramia fit:** ⭐⭐⭐⭐ — excellent use case pro cross-project patterns
- **Willingness to pay:** $99/mo Team tier
- **Where to find:** IndieHackers, ProductHunt, LinkedIn automation communities

#### ICP 3: Individual AI Developers / Researchers (VOLUME)
- **Profil:** Solo developer budující agent project na open-source frameworcích
- **Pain:** No persistent memory, opakování práce across experiments
- **Engramia fit:** ⭐⭐⭐ — Pro tier ($29) nebo Free OSS
- **Willingness to pay:** $0–$29/mo
- **Where to find:** HackerNews, Reddit /r/MachineLearning, GitHub

#### ICP 4: Enterprise (POST-LAUNCH)
- **Profil:** Velká firma, regulated industry, potřebuje compliance, SSO, audit logs
- **Pain:** Governance, scale, trust
- **Engramia fit:** ⭐⭐⭐ — základy jsou, ale SOC 2 + SAML + encryption at rest chybí
- **Willingness to pay:** $1k–$10k+/mo
- **When:** Post-launch, po SOC 2 Type II certifikaci

### Minimum Viable pro každý segment

| Segment | Minimum pro traction |
|---|---|
| ICP 1 (AI Platform Teams) | Cloud onboarding ✅ + GitHub Actions integration + Slack notifications + JS SDK |
| ICP 2 (Automation Studios) | Cloud onboarding ✅ + support channel + cross-project patterns + API docs site |
| ICP 3 (Solo Devs) | PyPI release ✅ + Docker Hub ✅ + Jupyter quickstart notebook + community Discord |
| ICP 4 (Enterprise) | SOC 2 + SAML SSO + dedicated CSM + SLA contract |

---

## F) Feature Priority Matrix

| Feature | Effort | Impact | Segment | Priority |
|---|---|---|---|---|
| Cloud onboarding flow (email signup → API key) | M | ⭐⭐⭐⭐⭐ | Všechny | **P0** |
| Public status page (Uptime Kuma → status.engramia.dev) | XS | ⭐⭐⭐⭐ | Všechny | **P0** |
| OG tags / Twitter cards / robots.txt / sitemap | XS | ⭐⭐⭐⭐ | Všechny | **P0** |
| PyPI environment protection (release gate) | XS | ⭐⭐⭐⭐ | Všechny | **P0** |
| Support email + GitHub Discussions setup | XS | ⭐⭐⭐⭐ | Všechny | **P0** |
| Legal attorney review (ToS, Privacy, DPA) | M (ext.) | ⭐⭐⭐⭐⭐ | Všechny | **P0** |
| Automated backup script (pg_dump cron) | S | ⭐⭐⭐⭐ | Ops | **P0** |
| Security scanning v CI (pip-audit / bandit) | S | ⭐⭐⭐ | Security | **P0** |
| Discord/Slack community | XS | ⭐⭐⭐⭐ | ICP 1,3 | **P1** |
| GitHub Actions integration (eval-on-PR) | M | ⭐⭐⭐⭐⭐ | ICP 1,3 | **P1** |
| JavaScript/TypeScript SDK | L | ⭐⭐⭐⭐⭐ | ICP 1,2,3 | **P1** |
| Slack/Discord webhook notifications | S | ⭐⭐⭐⭐ | ICP 1,2 | **P1** |
| Pattern detail view v admin dashboard | M | ⭐⭐⭐⭐ | ICP 1,2 | **P1** |
| Eval run comparison UI (A vs B) | M | ⭐⭐⭐⭐ | ICP 1 | **P1** |
| Eval dataset management (upload CSV/JSONL) | M | ⭐⭐⭐⭐ | ICP 1 | **P1** |
| Jupyter/Colab quickstart notebook | S | ⭐⭐⭐⭐ | ICP 3 | **P1** |
| OpenAI Agents SDK adapter | S | ⭐⭐⭐⭐⭐ | ICP 1,3 | **P1** |
| "93% success rate" hero stat na landing page | XS | ⭐⭐⭐⭐⭐ | Marketing | **P1** |
| Interactive playground / demo mode v dashboard | L | ⭐⭐⭐⭐ | ICP 1,3 | **P1** |
| SAML SSO | M | ⭐⭐⭐⭐ | ICP 4 | **P2** |
| Encryption at rest dokumentace + hardening | S | ⭐⭐⭐ | ICP 4 | **P2** |
| SOC 2 Type II příprava | XL (ext.) | ⭐⭐⭐⭐⭐ | ICP 4 | **P2** |
| Real-time eval streaming (SSE) | M | ⭐⭐⭐ | ICP 1 | **P2** |
| Redis-backed rate limiter | M | ⭐⭐⭐ | ICP 1 | **P2** |
| MRR dashboard (Stripe → Grafana) | S | ⭐⭐⭐ | Ops/Business | **P2** |
| Memory taxonomy (episodic/semantic/procedural) | L | ⭐⭐⭐ | ICP 1 | **P2** |
| Knowledge Graph layer | XL | ⭐⭐⭐⭐ | ICP 1,4 | **P2** |
| Dedicated vector DB (Qdrant/Milvus) backend | L | ⭐⭐⭐ | ICP 4 | **P2** |
| Multi-agent memory sharing | L | ⭐⭐⭐⭐ | ICP 1 | **P2** |
| Community patterns marketplace | XL | ⭐⭐⭐ | ICP 3 | **P3** |
| Multimodal memory (image/audio refs) | XL | ⭐⭐ | ICP 1 | **P3** |
| Reinforcement learning z eval scores | XL | ⭐⭐⭐ | ICP 1 | **P3** |

**Effort klíč:** XS = <1 den, S = 1–3 dny, M = 1–2 týdny, L = 1 měsíc, XL = 2+ měsíce

---

## G) Verdict

### Launch Now vs. Wait?

**Doporučení: Launch as Developer Preview NOW, Full Commercial Launch v 3–4 týdnech.**

#### Proč launcher developer preview hned:
1. **Core tech je ready.** 726 testů, 80%+ coverage, 3 audit cykly, všechny P0–P2 security findings resolved. Produkt funguje.
2. **PyPI + Docker + MCP** — library lze nainstalovat a používat dnes. Open-source komunita může začít adopt.
3. **Positioning je genuinely unique.** Nikdo jiný nedělá execution pattern memory + eval-weighted recall. Tohle okno se může zavřít.
4. **93% success rate claim** je validovaný benchmarkem — vzácná věc v AI tooling. Toto je marketing zlato.

#### Proč počkat s plným komerčním launchem:
1. **Cloud onboarding neexistuje** — bez signup flow nemůže žádný platící zákazník začít. Toto je P0 blocker pro revenue.
2. **Legal docs potřebují attorney review** — fakturace bez reviewed ToS/DPA je risk.
3. **Support channel neexistuje** — paying customers ($29+/mo) nemají kam napsat.

#### 3-týdenní sprint k full commercial launch:
| Týden | Priorita |
|---|---|
| Week 1 | Cloud onboarding (manual admin flow) + public status page + OG tags + Discord community + support email + PyPI release |
| Week 2 | Legal attorney review dokončit + GitHub Discussions + Slack webhook notification example + "93%" hero stat na landing |
| Week 3 | GitHub Actions integration OR JS SDK (podle zpětné vazby z early adopters) + public beta announcement |

---

### Top 3 věci které by nejvíce zvýšily šanci na úspěch

#### 1. Cloud onboarding + "First Success in 5 Minutes"
Engramia má výborný produkt, ale zákazník nikdy k "aha momentu" nedojde bez funkčního cloud signup. Implementace nemusí být složitá — manual admin flow (zákazník pošle email → admin vytvoří API key) stačí pro první desítky zákazníků. Kriticky důležité je také vytvořit **interaktivní Jupyter notebook** kde zákazník v 5 krocích vidí: `learn() → recall() → eval score roste`. Tohle je rozdíl mezi 2% a 15% activation rate.

#### 2. GitHub Actions Integration (`engramia/eval-action`)
AI platform teams žijí v CI/CD. Eval-on-PR je workflow který zákazníci od LangSmith a Braintrust znají a milují — ale tyto nástroje jsou buď LangChain-only nebo drahé. Engramia může zaujmout toto místo pro framework-agnostic use cases. Technicky relativně jednoduchá integrace (REST API volání z action), ale obrovský impact na adoption: developer vidí eval score ve svém PR výsledku a hned chápe hodnotu.

#### 3. Community + "93% Proof Story" Content
Největší risk u developer tools je obscurita. Engramia má naprosto unikátní příběh: *"Extracted from a self-improving agent factory that reached 93% success rate."* Toto je story která se sdílí. HackerNews post s benchmarkem, 3 blog posty (připravené), Product Hunt launch, a Discord komunita mohou v prvních 30 dnech přivést stovky early adopters. Bez aktivní komunity bude produkt neviditelný bez ohledu na technickou kvalitu.

---

## Appendix: Competitive Snapshot (2025–2026)

### Memory Layer
- **Mem0**: Convergenoval na personalized memory pro LLM apps. API-first, $0.01/1000 operations. Silný v consumer AI, slabý v enterprise/code agents.
- **Zep**: Temporal knowledge graph pro chat history. Cloud $0.10/user/month. Niche: conversational AI.
- **LangMem** (LangChain): Open-source, tight LangGraph coupling. Threat pro LangChain users, ne pro framework-agnostic.
- **MemGPT/Letta**: Research → product. Complex agent framework s memory jako první-class citizen. Těžší adoption curve.

### Eval Platforms
- **LangSmith**: Průmyslový standard pro LangChain ecosystem. $39/mo teams. Complaints: přehnaně drahé pro high-volume, LangChain vendor lock-in.
- **Braintrust**: Strong human eval UX. $20/user/month. Rychle roste u AI product teams. Omezená free tier.
- **DeepEval**: Python-first, OSS. Výborný DX, populární u developers. Chybí memory/learning component.
- **LangFuse**: OSS observability + eval. Silný self-hosted story, aktivní komunita. Opravdový competitor v enterprise segment.
- **Ragas**: Dominantní v RAG eval. Nepoužitelný mimo RAG.
- **Patronus AI**: Enterprise-only, $500+/mo, focus na safety. Enterprise segment.

### Observability
- **LangFuse**: Traces, evals, dataset management v jednom. $10+/mo. Open-source. Nejbližší celkový competitor.
- **Helicone**: Proxy-based, jednoduchý setup. $20+/mo. Dobrý DX ale jen observability, ne memory/eval.
- **Phoenix Arize**: ML + LLM observability. Enterprise-first.

### Engramia Unikátní Výhody vs. celý trh
1. Jediný produkt kombinující **execution memory + eval-weighted recall**
2. Jediný s **time-decay aging** (paměť zastarává jako u lidí)
3. Jediný s **adversarial pattern detection**
4. Validovaný vlastním agentem v produkci (**93% claim s benchmarkem**)
5. **MCP server** — zatím nikdo jiný nemá native MCP integrace v tomto space

---

*Report zpracován: 2026-04-05*
*Verze produktu: v0.6.5*
*Doporučení: Developer Preview launch ASAP, Full Commercial Launch za 3–4 týdny po dořešení P0 blockerů*
