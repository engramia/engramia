# Records of Processing Activities (RoPA)

**Controller:** Marek Čermák, OSVČ (sole trader), Czech Republic
**Document version:** 1.0
**Date:** 2026-04-05
**Legal basis reference:** GDPR Art. 30(1)

> This document is an internal record of processing activities. It is not published publicly but must be made available to supervisory authorities (ÚOOÚ) upon request.

---

## 1. User Account Registration & Authentication

| Field | Details |
|---|---|
| **Purpose** | Creating and managing user accounts; authenticating access to the Engramia cloud service |
| **Legal basis** | Art. 6(1)(b) — performance of a contract |
| **Data categories** | Email address, hashed password (bcrypt), tenant identifier, account creation timestamp, last login timestamp, OAuth provider identifier (if Google/GitHub login used) |
| **Data subjects** | Registered users (developers, businesses) |
| **Recipients** | Hetzner (infrastructure hosting, DE); Stripe (billing, see #4) |
| **Retention** | Account data: duration of subscription + 30 days after account deletion; email: retained for 5 years for billing audit trail |
| **Cross-border transfer** | None for this activity (Hetzner DE only) |
| **Technical measures** | bcrypt password hashing; TLS 1.3 in transit; PostgreSQL access restricted to internal Docker network |

---

## 2. Agent Execution Pattern Storage

| Field | Details |
|---|---|
| **Purpose** | Storing and retrieving AI agent execution patterns to enable memory and recall functionality — the core service |
| **Legal basis** | Art. 6(1)(b) — performance of a contract |
| **Data categories** | Pattern content (arbitrary text submitted by users — **may contain personal data if user's agent processes personal data**), evaluation scores, metadata (timestamps, project ID, tenant ID), vector embeddings |
| **Data subjects** | Indirect — data subjects of the Engramia customer's end users (Engramia is a data processor in this relationship; customer is the controller) |
| **Recipients** | Hetzner (infrastructure, DE); OpenAI Inc. (USA) for vector embedding generation; optionally Anthropic PBC (USA) for LLM evaluation |
| **Retention** | Per customer configuration; default: retained until explicitly deleted; max retention configurable via `expires_at`; deleted within 30 days after account termination |
| **Cross-border transfer** | **USA (OpenAI, Anthropic)** — Standard Contractual Clauses (SCCs) under GDPR Art. 46(2)(c) |
| **Technical measures** | PII redaction enabled by default (`ENGRAMIA_REDACTION=true`); tenant isolation; pgvector with access controls; TLS in transit |

---

## 3. API Usage Logs & Audit Trail

| Field | Details |
|---|---|
| **Purpose** | Security monitoring, abuse prevention, debugging, compliance audit trail |
| **Legal basis** | Art. 6(1)(f) — legitimate interests (security and fraud prevention) |
| **Data categories** | IP address, API key prefix (not full key), HTTP method, endpoint path, response status code, request timestamp, tenant ID, user agent string |
| **Data subjects** | Registered users and any system making API calls |
| **Recipients** | Hetzner (infrastructure, DE); Grafana/Loki for log aggregation (self-hosted, same DE VPS) |
| **Retention** | Access logs: 90 days; audit log (security events): 2 years |
| **Cross-border transfer** | None (self-hosted monitoring on Hetzner DE) |
| **Technical measures** | Logs stored locally; no external log aggregation service; structured JSON logging without full request body by default |

---

## 4. Billing & Payment Data

| Field | Details |
|---|---|
| **Purpose** | Processing subscription payments; managing billing lifecycle (upgrades, downgrades, dunning) |
| **Legal basis** | Art. 6(1)(b) — performance of a contract; Art. 6(1)(c) — legal obligation (accounting records) |
| **Data categories** | Email address, Stripe Customer ID, subscription tier, subscription status, payment method last 4 digits (held by Stripe, not Engramia), invoice history |
| **Data subjects** | Paying subscribers |
| **Recipients** | Stripe, Inc. (USA/Ireland) — payment processor; Stripe is EU-US Data Privacy Framework certified and provides a DPA |
| **Retention** | Billing records: 10 years (Czech accounting law — zákon č. 563/1991 Sb.); Stripe data: per Stripe's retention policy |
| **Cross-border transfer** | **USA (Stripe)** — EU-US Data Privacy Framework; Stripe DPA available at https://stripe.com/legal/dpa |
| **Technical measures** | Engramia does not store raw payment card data; all payment processing via Stripe Checkout (SAQ A scope); webhook signature verification |

---

## 5. Support Communications

| Field | Details |
|---|---|
| **Purpose** | Responding to user support requests, bug reports, and feature requests |
| **Legal basis** | Art. 6(1)(f) — legitimate interests (customer support) |
| **Data categories** | Email address, message content, any attachments voluntarily provided |
| **Data subjects** | Users who contact support |
| **Recipients** | Email provider (Seznam.cz or equivalent, CZ/EU) |
| **Retention** | Support emails: 2 years after last contact |
| **Cross-border transfer** | None if using EU email provider |
| **Technical measures** | Standard email encryption (TLS); no ticketing system with third-party data sharing at this time |

---

## 6. Website Analytics (Optional)

| Field | Details |
|---|---|
| **Purpose** | Understanding website traffic to improve product and marketing |
| **Legal basis** | Art. 6(1)(a) — consent (opt-in only; no tracking without consent) |
| **Data categories** | Page views, referrer, approximate location (country-level), device type — no cross-site tracking |
| **Data subjects** | Website visitors who opt in |
| **Recipients** | Self-hosted analytics only (no Google Analytics, no third-party trackers) |
| **Retention** | Aggregated, anonymized; individual session data max 30 days |
| **Cross-border transfer** | None |
| **Technical measures** | No cookies without consent; no fingerprinting |

---

## Data Subject Rights — Process

All requests from data subjects are handled per GDPR Art. 15–22:

1. Request received at `support@engramia.dev`
2. Identity verified (must match registered email)
3. Response within **30 days** (Art. 12(3))
4. For erasure: data deleted from all systems within 30 days; backups overwritten within 60 days
5. DSR requests tracked in internal DSR queue (`governance/dsr.py`)

---

## Sub-processor List

| Sub-processor | Country | Purpose | Legal basis for transfer |
|---|---|---|---|
| Hetzner Online GmbH | Germany (DE) | Infrastructure hosting, block storage | Within EU — no transfer |
| Stripe, Inc. | USA / Ireland | Payment processing | EU-US DPF + DPA |
| OpenAI, Inc. | USA | LLM inference, embeddings | Standard Contractual Clauses |
| Anthropic, PBC | USA | Alternative LLM inference | Standard Contractual Clauses |

---

## Review Schedule

This document shall be reviewed and updated:
- At least annually (next review: 2027-04-05)
- Upon any material change to processing activities
- Upon any new sub-processor engagement
- Upon any data breach

**Last reviewed:** 2026-04-05 by Marek Čermák
