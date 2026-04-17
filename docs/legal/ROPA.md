# Records of Processing Activities — Public Summary

**Controller:** Engramia (Marek Čermák, sole trader), Czech Republic
**Last updated:** 2026-04-09
**Legal basis reference:** GDPR Art. 30

> This is a public summary of our processing activities. The full internal
> RoPA is maintained separately and available to supervisory authorities
> (ÚOOÚ) upon request as required by GDPR Art. 30(4).

---

## Processing Activities Overview

### 1. User Account Registration & Authentication

| Field | Details |
|---|---|
| **Purpose** | Creating and managing user accounts; authenticating access to the Engramia service |
| **Legal basis** | Art. 6(1)(b) — performance of a contract |
| **Data categories** | Email address, hashed password, account metadata (creation date, last login) |
| **Data subjects** | Registered users (developers, businesses) |
| **Retention** | Duration of subscription + 30 days after account deletion |
| **Cross-border transfer** | None (EU infrastructure) |

### 2. Agent Execution Pattern Storage (Core Service)

| Field | Details |
|---|---|
| **Purpose** | Storing and retrieving AI agent execution patterns — the core memory and recall functionality |
| **Legal basis** | Art. 6(1)(b) — performance of a contract |
| **Data categories** | Pattern content (text submitted by users), evaluation scores, metadata, vector embeddings |
| **Data subjects** | Indirect — data subjects of customer's end users (Engramia acts as data processor; customer is the controller) |
| **Retention** | Per customer configuration; default: retained until explicitly deleted; removed within 30 days after account termination |
| **Cross-border transfer** | USA (LLM providers) — Standard Contractual Clauses / EU-US Data Privacy Framework |

### 3. API Usage Logs & Audit Trail

| Field | Details |
|---|---|
| **Purpose** | Security monitoring, abuse prevention, compliance audit trail |
| **Legal basis** | Art. 6(1)(f) — legitimate interests (security) |
| **Data categories** | IP address, API key prefix, request metadata (method, endpoint, status code, timestamp) |
| **Data subjects** | API users |
| **Retention** | Access logs: 90 days; security audit events: 2 years |
| **Cross-border transfer** | None (self-hosted monitoring within EU) |

### 4. Billing & Payment Data

| Field | Details |
|---|---|
| **Purpose** | Processing subscription payments and managing billing lifecycle |
| **Legal basis** | Art. 6(1)(b) — contract; Art. 6(1)(c) — legal obligation (accounting) |
| **Data categories** | Email address, subscription tier and status, invoice history |
| **Data subjects** | Paying subscribers |
| **Retention** | Billing records: 10 years (Czech accounting law) |
| **Cross-border transfer** | USA/Ireland (payment processor) — EU-US Data Privacy Framework |

> Engramia does not store payment card data. All payment processing is handled
> by our PCI-compliant payment processor (Stripe).

### 5. Support Communications

| Field | Details |
|---|---|
| **Purpose** | Responding to support requests, bug reports, feature requests |
| **Legal basis** | Art. 6(1)(f) — legitimate interests (customer support) |
| **Data categories** | Email address, message content, voluntary attachments |
| **Data subjects** | Users who contact support |
| **Retention** | 2 years after last contact |
| **Cross-border transfer** | None (EU email provider) |

### 6. Website Analytics

| Field | Details |
|---|---|
| **Purpose** | Understanding website traffic to improve product |
| **Legal basis** | Art. 6(1)(a) — consent (opt-in only) |
| **Data categories** | Page views, referrer, approximate location (country), device type |
| **Data subjects** | Website visitors who opt in |
| **Retention** | Aggregated/anonymized; individual session data max 30 days |
| **Cross-border transfer** | None (self-hosted analytics) |

> No tracking occurs without explicit consent. No third-party trackers are used.

---

## Sub-processors

For the current list of sub-processors, see [SUBPROCESSORS.md](SUBPROCESSORS.md).

---

## Data Subject Rights

You may exercise your rights under GDPR Articles 15–22 (access, rectification,
erasure, portability, restriction, objection) by contacting us at:

**Email:** support@engramia.dev

We will verify your identity and respond within **30 days** as required by
Art. 12(3). For erasure requests, data is removed from all active systems within
30 days and from backups within 60 days.

---

## Review Schedule

This document is reviewed and updated:

- At least annually
- Upon any material change to processing activities
- Upon engagement of a new sub-processor
- Upon any data breach

For questions about our data processing practices, contact support@engramia.dev.
