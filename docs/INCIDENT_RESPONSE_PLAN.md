# Incident Response Plan — Engramia

| | |
|---|---|
| **Version** | 1.0.0 |
| **Effective date** | 2026-04-07 |
| **Owner** | Marek (solo founder) |
| **Review cycle** | Annual (next: 2027-04-07) |
| **Related documents** | `SECURITY.md`, `monitoring/alerts.rules.yml`, `docs/disaster-recovery.md` |

---

## 1. Purpose and Scope

This Incident Response Plan (IRP) defines how Engramia detects, contains, investigates, and recovers from operational and security incidents. It also specifies how the company meets its GDPR obligations under Czech and EU law when a personal data breach occurs.

**In scope:**

- All components of the Engramia SaaS platform (API, PostgreSQL/pgvector, LLM integrations, Stripe billing, monitoring stack)
- Infrastructure hosted on Hetzner Cloud, Frankfurt, DE
- Data processed on behalf of customers (API keys, agent execution logs, stored memory patterns)
- Third-party integrations (LLM providers, Stripe)

**Out of scope:**

- Customer-side incidents in systems not operated by Engramia
- Issues arising from customer misconfiguration of self-hosted deployments

---

## 2. Severity Levels

### Severity Matrix

| Level | Name | Definition | Initial Response | Resolution Target |
|---|---|---|---|---|
| **P1** | Critical | Complete service outage **or** confirmed data breach affecting customer data | **15 minutes** | 4 hours |
| **P2** | High | Significant degradation (error rate >10%, p95 latency >5 s sustained), partial data loss, security vulnerability with active exploitation risk | **30 minutes** | 8 hours |
| **P3** | Medium | Degraded performance (elevated latency, high queue depth), non-critical component failure, suspected (unconfirmed) security event | **2 hours** | 24 hours |
| **P4** | Low | Minor anomaly, cosmetic issue, warning-level alert that has not escalated, post-incident follow-up work | **Next business day** | 72 hours |

### Alert-to-Severity Mapping

The following table maps Alertmanager rules (`monitoring/alerts.rules.yml`) to severity levels:

| Alert | Default P-Level |
|---|---|
| `EngramiaDown` | P1 |
| `HighErrorRate` (>10 %) | P1 |
| `ZeroPatterns` | P1 |
| `DBPoolExhausted` | P1 |
| `CriticalDiskUsage` (>95 %) | P1 |
| `LLMProviderDown` (>50 % error rate) | P1 |
| `JobQueueDepthCritical` (>200) | P1 |
| `JobProcessingLatencyCritical` (p95 >120 s) | P1 |
| `HighRequestLatency` (p95 >5 s) | P2 |
| `HighLLMLatency` (p95 >30 s) | P2 |
| `HighDBPoolUsage` (>80 %) | P2 |
| `HighDiskUsage` (>85 %) | P2 |
| `LLMProviderErrors` (>10 %) | P2 |
| `JobQueueDepthHigh` (>50) | P2 |
| `JobProcessingLatencyHigh` (p95 >30 s) | P2 |
| `LowSuccessRate` (<50 %) | P3 |
| `LowEvalScore` (<3/10) | P3 |
| `HighRecallMissRate` (>80 %) | P3 |
| `StripeWebhookErrors` | P3 |
| `JobStuckOrFailed` | P3 |

---

## 3. Incident Detection Sources

### 3.1 Automated Monitoring

- **Prometheus + Alertmanager** — fires alerts defined in `monitoring/alerts.rules.yml`; routes to PagerDuty / email / Slack as configured in `monitoring/alertmanager.yml`
- **Grafana dashboards** — `monitoring/grafana/provisioning/dashboards/engramia-overview.json` for visual triage
- **Uptime monitoring** — external probe (e.g., Hetzner or BetterUptime) for black-box health checks independent of the internal stack
- **Docker health checks** — container restarts surfaced via Coolify and Docker Compose restart policies

### 3.2 Customer Reports

- Support email or in-product feedback channel
- GitHub Issues (for open-source/self-hosted users)
- Direct contact from enterprise customers

### 3.3 Security Scans

- Dependency vulnerability scans (`pip audit`, Dependabot alerts on GitHub)
- Periodic manual penetration testing
- GitHub secret scanning and push protection
- Review of Hetzner security advisories

### 3.4 Third-Party Notifications

- Hetzner infrastructure alerts (hardware, DDoS, network)
- LLM provider status pages (OpenAI, Anthropic, etc.)
- Stripe status page and webhook delivery failure alerts

---

## 4. Escalation Chain

Because Engramia is operated by a solo founder, the escalation chain is intentionally flat.

```
Automated Alert / Customer Report
         │
         ▼
   Marek (Primary On-Call)
   ─────────────────────────────────────────────────────────
   • Triages every incoming alert
   • Owns all P1–P4 incidents end-to-end
   • Makes final decision on customer and regulatory communications
         │
         │  (if P1 security incident beyond solo capacity)
         ▼
   External Security Consultant (ad-hoc engagement)
   • Engaged for: active breach forensics, malware analysis,
     penetration test findings requiring immediate remediation
   • Contact maintained in a private, encrypted note outside this repo
         │
         │  (if GDPR personal data breach confirmed)
         ▼
   ÚOOÚ (Czech Data Protection Authority)
   • Mandatory notification ≤ 72 h from discovery
   • See Section 6 for full procedure
```

**Note:** If Marek is unreachable for more than 1 hour during a P1/P2 incident and the external security consultant cannot be reached, the fallback is to put the service into maintenance mode (return HTTP 503) to limit blast radius until the incident can be handled properly.

---

## 5. Response Procedures by Severity

### P1 — Critical

1. **Acknowledge** the alert within 15 minutes.
2. **Triage** — confirm the incident is real (not a monitoring false positive). Check Grafana dashboard, application logs, and Hetzner status page.
3. **Contain** — if data exfiltration or active breach is suspected, isolate immediately:
   - Rotate all `ENGRAMIA_API_KEYS`
   - Block offending IPs at Hetzner firewall level
   - If necessary, shut down the API container (`docker compose stop engramia-api`)
4. **Notify customers** — post a status page update within 30 minutes of confirmation (see template in Section 7).
5. **Investigate and remediate** — follow applicable runbook in `docs/runbooks/`.
6. **Restore service** — perform staged restore; validate with health endpoint and smoke tests.
7. **Document** — capture timeline, root cause, and actions taken in the post-mortem template (Section 8).
8. **GDPR check** — if any personal data was involved, immediately initiate Section 6 process.

### P2 — High

1. **Acknowledge** within 30 minutes.
2. **Triage** — determine scope and whether the issue is worsening or stable.
3. **Mitigate** — apply workaround if available (e.g., restart stuck workers, increase pool size, switch LLM provider).
4. **Monitor** — confirm mitigation is effective; check that alerts resolve.
5. **Notify customers** if the degradation is customer-visible and ongoing for >30 minutes.
6. **Root-cause fix** — schedule within the 8-hour window.
7. **Document** — brief post-mortem for any P2 that lasted >1 hour.

### P3 — Medium

1. **Acknowledge** within 2 hours.
2. **Investigate** — determine if the issue will self-resolve or requires action.
3. **Fix or schedule** — apply fix immediately if low-risk, otherwise schedule in next working session.
4. **Document** — note in incident log; full post-mortem optional.

### P4 — Low

1. **Log** — record the alert or report.
2. **Prioritize** — add to backlog with appropriate priority.
3. **Resolve** — address within 72 hours.
4. **No customer communication** required unless the issue becomes visible.

---

## 6. GDPR Breach Notification Process

This section applies whenever an incident involves or may involve unauthorized access to, disclosure of, loss of, or destruction of personal data processed by Engramia on behalf of data subjects.

### 6.1 Personal Data in Scope

Engramia stores and processes:
- Customer account information (email, billing details via Stripe)
- Agent execution data submitted by customers (may contain end-user data depending on customer's use case)
- API keys and authentication tokens
- IP addresses and request metadata in access logs

### 6.2 Internal Assessment (within 24 hours of discovery)

Assess and document:

| Question | Notes |
|---|---|
| What data was involved? | Category, fields, estimated volume |
| How many data subjects are affected? | Estimate if exact count unknown |
| What was the nature of the breach? | Unauthorized access / accidental disclosure / loss / destruction |
| What is the likely impact on data subjects? | Low / Medium / High risk |
| Has the breach been contained? | Yes / No / In progress |
| What is the root cause? | Technical vulnerability / human error / external attack |

**Decision gate:** If impact on data subjects is assessed as **anything other than "unlikely to result in a risk"**, ÚOOÚ notification is mandatory. When in doubt, notify.

### 6.3 ÚOOÚ Notification (within 72 hours of discovery)

The 72-hour clock starts from the moment the breach was **first discovered**, not when it was fully investigated.

**Mandatory fields per GDPR Article 33:**
1. Nature of the personal data breach
2. Categories and approximate number of data subjects concerned
3. Categories and approximate number of personal data records concerned
4. Name and contact details of the data protection contact (Marek)
5. Likely consequences of the breach
6. Measures taken or proposed to address the breach

**Submission method:**
- Email: posta@uoou.gov.cz
- Post: Úřad pro ochranu osobních údajů, Pplk. Sochora 27, 170 00 Praha 7
- Online portal: https://www.uoou.cz (if electronic notification is accepted for the incident type)

See Section 7.3 for the Czech-language notification template.

**If the 72-hour deadline cannot be met:** Submit a partial notification before the deadline with all information available at that time, and explicitly state that the investigation is ongoing. Send a supplement as soon as additional information is available.

### 6.4 Data Subject Notification (if high risk)

If the breach is likely to result in a **high risk** to the rights and freedoms of data subjects (GDPR Article 34), notify affected data subjects **without undue delay**:

- Contact via the email address on record
- Describe the nature of the breach in plain language
- Provide name and contact details of the DPC (Marek)
- Describe likely consequences
- Describe measures taken or recommended for data subjects
- Do **not** use security-through-obscurity; be direct and accurate

Notification may be omitted if:
- The data was encrypted and the key was not compromised, or
- Subsequent measures have ensured the high risk no longer materialises, or
- Individual notification would involve disproportionate effort (in which case a public communication is required instead)

### 6.5 Breach Record

Maintain an internal breach register regardless of whether external notification is required (GDPR Article 33(5)). Record:
- Date and time of discovery
- Date and time of containment
- Nature and scope of the breach
- Assessment rationale (notify / not notify)
- Actions taken
- Outcome

---

## 7. Communication Templates

### 7.1 Status Page Update

```
[STATUS] [INCIDENT TITLE] — [DATE UTC]

Status: Investigating / Identified / Monitoring / Resolved

Summary:
We are currently [investigating / experiencing] [brief description of impact].
[Affected functionality: list here.]

Impact:
[Who is affected and how. Be specific but avoid disclosing security details.]

Timeline:
- HH:MM UTC — Incident detected
- HH:MM UTC — [Action taken]
- HH:MM UTC — [Update]

Next update: [time]

We apologize for the inconvenience and will provide updates every [30 / 60] minutes.
```

### 7.2 Customer Notification (Email)

**Subject:** `[Engramia] Service Incident — [DATE] — [Brief Title]`

```
Hello,

We are writing to inform you of an incident affecting the Engramia service
that occurred on [DATE] between approximately [START TIME UTC] and [END TIME UTC].

What happened:
[1–3 sentences describing the incident in plain language. No technical jargon.]

Impact to your account:
[Was your data or service affected? Be specific. If unknown, say so.]

What we did:
[Steps taken to resolve the incident and prevent recurrence.]

What you should do:
[Any action required by the customer, e.g., rotate API keys, re-submit failed requests.]
[If no action required, state: No action is required on your part.]

We take the reliability and security of Engramia seriously and sincerely
apologize for any disruption this may have caused.

If you have any questions, please reply to this email.

Marek
Engramia
```

### 7.3 ÚOOÚ Notification Template (Czech)

**Předmět:** `Oznámení porušení zabezpečení osobních údajů dle čl. 33 GDPR — Engramia`

```
Úřad pro ochranu osobních údajů
Pplk. Sochora 27
170 00 Praha 7
posta@uoou.gov.cz

V [MÍSTO], dne [DATUM]

Věc: Oznámení porušení zabezpečení osobních údajů dle článku 33 nařízení
(EU) 2016/679 (GDPR)

Správce osobních údajů:
Jméno: [JMÉNO A PŘÍJMENÍ ZAKLADATELE]
Obchodní firma: Engramia
Adresa: [ADRESA]
E-mail: [KONTAKTNÍ E-MAIL]
Tel.: [TELEFON]

---

1. POVAHA PORUŠENÍ

Dne [DATUM ZJIŠTĚNÍ] v [ČAS] UTC bylo zjištěno porušení zabezpečení
osobních údajů spočívající v [stručný popis: např. neoprávněném přístupu k
databázi / náhodném zpřístupnění dat třetí straně / ztrátě dat].

Příčina incidentu: [technická zranitelnost / lidská chyba / kybernetický
útok zvenčí — stručný popis].

---

2. KATEGORIE A PŘIBLIŽNÝ POČET DOTČENÝCH SUBJEKTŮ ÚDAJŮ

Kategorie subjektů: [zákazníci – fyzické osoby / kontaktní osoby
zákazníků – právnické osoby / jiné]

Přibližný počet dotčených subjektů: [POČET nebo „v šetření"]

---

3. KATEGORIE A PŘIBLIŽNÝ POČET DOTČENÝCH ZÁZNAMŮ

Kategorie údajů: [e-mailové adresy / fakturační údaje / přístupové tokeny
/ metadata požadavků / jiné]

Přibližný počet záznamů: [POČET nebo „v šetření"]

---

4. PRAVDĚPODOBNÉ DŮSLEDKY PORUŠENÍ

[Popis potenciálního dopadu na dotčené subjekty, např.: riziko neoprávněného
přístupu k účtům, zneužití e-mailových adres k phishingu, finanční škoda apod.
Pokud jsou důsledky omezené, uveďte proč.]

Hodnocení rizika pro subjekty: Nízké / Střední / Vysoké

---

5. PŘIJATÁ A NAVRHOVANÁ OPATŘENÍ

Přijatá opatření:
- [DATUM ČAS UTC] — Incident zjištěn
- [DATUM ČAS UTC] — [Popis opatření, např. rotace API klíčů, izolace serveru]
- [DATUM ČAS UTC] — [Popis opatření]
- [DATUM ČAS UTC] — Únik/přístup zastaven

Plánovaná opatření k zamezení opakování:
- [Technická opatření]
- [Procesní opatření]

---

6. DOPLŇUJÍCÍ INFORMACE

[Pokud oznámení není úplné z důvodu probíhajícího šetření, uveďte zde:
„Šetření incidentu k datu tohoto oznámení stále probíhá. Doplňující informace
budou zaslány neprodleně po jejich zjištění, nejpozději do [DATUM]."]

---

S pozdravem,

[JMÉNO A PŘÍJMENÍ]
Engramia — správce osobních údajů
[E-MAIL] | [TELEFON]
[DATUM]
```

---

## 8. Post-Incident Review (Post-Mortem) Template

Post-mortems are **required** for all P1 incidents and P2 incidents lasting >1 hour. They are **optional but recommended** for P3 incidents with systemic root causes.

Post-mortems are blameless. The goal is to improve systems and processes, not to assign fault.

```markdown
# Post-Mortem: [Incident Title]

**Date of incident:** YYYY-MM-DD
**Duration:** HH:MM – HH:MM UTC (X hours Y minutes)
**Severity:** P1 / P2 / P3
**Author:** Marek
**Review date:** [Within 5 business days of resolution]

---

## Summary

[2–4 sentences describing what happened, what the impact was, and how it was resolved.]

---

## Impact

- **Service availability:** [% downtime or degraded window]
- **Customers affected:** [Number or percentage, if known]
- **Data affected:** [Yes / No — if yes, describe and cross-reference GDPR section]
- **Revenue impact:** [Estimated lost transactions, refunds issued]

---

## Timeline

| Time (UTC) | Event |
|---|---|
| HH:MM | Incident started / anomaly first occurred |
| HH:MM | Alert fired / customer report received |
| HH:MM | Marek acknowledged |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied |
| HH:MM | Service restored |
| HH:MM | Incident closed |

---

## Root Cause

[Describe the technical or process root cause. Be specific. What failed, and why?]

---

## Contributing Factors

- [Factor 1]
- [Factor 2]

---

## What Went Well

- [Detection was fast because...]
- [Runbook X was accurate and saved time]

---

## What Went Poorly

- [Alert threshold too high, delayed detection by X minutes]
- [No runbook existed for this failure mode]

---

## Action Items

| # | Action | Owner | Priority | Due date |
|---|---|---|---|---|
| 1 | [Specific, measurable improvement] | Marek | P1/P2/P3 | YYYY-MM-DD |
| 2 | | | | |

---

## Lessons Learned

[1–3 key takeaways for future reference.]
```

---

## 9. Annual Testing Schedule

The following activities must be completed once per calendar year to validate that this plan remains accurate and effective.

| Activity | Description | Target date | Completed |
|---|---|---|---|
| **Plan review** | Re-read this document; update contacts, thresholds, and procedures to reflect current architecture | Q1 (April) | |
| **Alert test** | Simulate a P1 alert (e.g., stop the API container) and verify Alertmanager fires and routes correctly | Q1 (April) | |
| **Communication drill** | Draft a status page update and customer notification for a hypothetical incident; review for clarity | Q2 (July) | |
| **GDPR drill** | Walk through the Section 6 process for a hypothetical data breach; verify ÚOOÚ template is current | Q2 (July) | |
| **Disaster recovery test** | Execute a restore from backup per `docs/disaster-recovery.md`; verify RTO/RPO targets | Q3 (October) | |
| **Runbook audit** | Verify all runbooks in `docs/runbooks/` are accurate against the current deployment | Q3 (October) | |
| **External consultant check-in** | Confirm external security consultant contact details are current and engagement terms are in place | Q4 (January) | |

---

## 10. Document Version History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0.0 | 2026-04-07 | Marek | Initial version |
