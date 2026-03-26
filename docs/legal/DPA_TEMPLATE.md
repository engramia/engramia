# Data Processing Agreement (DPA)

**Engramia — Self-Learning Memory Layer for AI Agents**

Template version: 2026-03-23

> **Note:** This is a template. Each DPA must be individually executed between the Licensor and the Customer. This document is provided as a starting point and should be reviewed by legal counsel before execution. DPA agreements are available as part of the Enterprise tier and may be subject to additional fees.

---

**This Data Processing Agreement** ("DPA") is entered into between:

**Data Controller:**
[Customer Name]
[Customer Address]
("Controller", "Customer")

**Data Processor:**
Marek Čermák
Czech Republic
("Processor", "Licensor")

This DPA supplements the Terms of Service ("ToS") and Privacy Policy governing the Customer's use of Engramia (the "Service"). In the event of conflict between this DPA and the ToS, this DPA shall prevail with respect to the processing of personal data.

---

## 1. Definitions

Terms used in this DPA have the meanings given in the GDPR (Regulation (EU) 2016/679) unless otherwise defined:

- **"Personal Data"** — any information relating to an identified or identifiable natural person.
- **"Processing"** — any operation performed on Personal Data (collection, storage, retrieval, use, disclosure, erasure, etc.).
- **"Sub-processor"** — any third party engaged by the Processor to process Personal Data on behalf of the Controller.
- **"Data Breach"** — a breach of security leading to accidental or unlawful destruction, loss, alteration, unauthorized disclosure of, or access to Personal Data.

## 2. Scope and Purpose of Processing

### 2.1 Subject Matter

The Processor processes Personal Data on behalf of the Controller solely to provide the Engramia Service as described in the ToS.

### 2.2 Nature and Purpose

| Processing Activity | Purpose |
|---------------------|---------|
| Storage of Customer Data (patterns, tasks, code, evaluations) | Providing the core Service (learn, recall, compose, evaluate) |
| Embedding generation | Semantic search functionality |
| API request logging (IP address, timestamps) | Security, rate limiting, abuse prevention |
| Transmission to third-party AI model providers | AI inference (evaluate, compose, evolve) — only when initiated by Controller |

### 2.3 Categories of Data Subjects

As determined by the Controller. May include:
- Controller's employees and contractors
- Controller's end users
- Other individuals whose data is included in Customer Data

### 2.4 Types of Personal Data

As determined by the Controller. May include:
- Names, email addresses, or identifiers embedded in task descriptions or code
- Technical data (IP addresses)
- Any other personal data the Controller submits as Customer Data

### 2.5 Duration

Processing continues for the duration of the Controller's Subscription, plus the data retention period specified in the ToS (30 days grace + 60 days retrieval + deletion).

## 3. Controller Obligations

The Controller shall:
- Ensure it has a lawful basis for processing Personal Data through the Service.
- Ensure it has provided appropriate notices to data subjects and obtained necessary consents.
- Ensure Customer Data submitted to the Service does not violate applicable law.
- Provide documented instructions for processing (the ToS and this DPA constitute such instructions).
- Promptly notify the Processor of any data subject requests it cannot fulfill independently.

## 4. Processor Obligations

The Processor shall:

### 4.1 Processing Instructions
- Process Personal Data only on documented instructions from the Controller (as set out in this DPA and the ToS), unless required by applicable law.
- Immediately inform the Controller if, in the Processor's opinion, an instruction infringes GDPR or other applicable data protection law.

### 4.2 Confidentiality
- Ensure that all personnel authorized to process Personal Data are bound by confidentiality obligations.

### 4.3 Security Measures
- Implement appropriate technical and organizational measures to ensure a level of security appropriate to the risk, including:

| Measure | Implementation |
|---------|---------------|
| Encryption in transit | TLS/HTTPS for all API communication |
| Authentication | Bearer token with timing-safe comparison (HMAC) |
| Access control | API key-based authentication, rate limiting |
| Input validation | Strict validation on all inputs (length limits, type checks, path traversal prevention) |
| Audit logging | Structured JSON logs for security events |
| Hashed credentials | API keys stored as SHA-256 hashes |
| Container security | Non-root Docker containers |
| Request limits | Body size limits, rate limiting per IP and endpoint |

For a complete description, see the Engramia [Security Policy](../../SECURITY.md).

### 4.4 Sub-processors
- Not engage any Sub-processor without prior specific or general written authorization from the Controller.
- When general authorization is granted, inform the Controller of any intended addition or replacement of Sub-processors, giving the Controller the opportunity to object.
- Ensure Sub-processors are bound by data protection obligations no less protective than those in this DPA.

**Current Sub-processors:**

| Sub-processor | Purpose | Location |
|---------------|---------|----------|
| [Cloud hosting provider — TBD] | Infrastructure hosting | EU |
| [Payment processor — TBD] | Billing and payments | EU/US |
| OpenAI (if configured by Controller) | AI model inference | US |
| Anthropic (if configured by Controller) | AI model inference | US |

The Controller acknowledges that AI model providers are engaged only when the Controller configures and initiates API calls that require AI inference (evaluate, compose, evolve). If the Controller uses local embeddings and a self-hosted LLM, no data is transmitted to AI model providers.

### 4.5 Data Subject Rights
- Assist the Controller in responding to data subject requests (access, rectification, erasure, portability, restriction, objection) by appropriate technical and organizational measures.
- Provide data export in structured, machine-readable format (JSON) upon request.

### 4.6 Data Breach Notification
- Notify the Controller without undue delay (and in any event within 72 hours) after becoming aware of a Data Breach.
- Provide the Controller with sufficient information to meet its obligations under GDPR Article 33 (notification to supervisory authority) and Article 34 (notification to data subjects), including:
  - Nature of the breach
  - Categories and approximate number of data subjects affected
  - Likely consequences
  - Measures taken or proposed to address the breach

### 4.7 Data Protection Impact Assessment
- Assist the Controller, upon request, with data protection impact assessments (DPIA) and prior consultations with supervisory authorities, to the extent required by GDPR Articles 35 and 36.

### 4.8 Deletion and Return
- Upon termination of the Service, delete or return all Personal Data to the Controller, at the Controller's choice, in accordance with the retention schedule in the ToS (Section 6.5).
- Certify deletion in writing upon request.

## 5. International Data Transfers

### 5.1 Primary Processing Location
Personal Data is primarily processed within the EU/EEA.

### 5.2 Transfers Outside EU/EEA
Transfers to Sub-processors outside the EU/EEA (including AI model providers in the US) are governed by:
- EU-US Data Privacy Framework (where applicable), or
- Standard Contractual Clauses (SCCs) as adopted by the European Commission (Decision 2021/914), or
- Other legally recognized transfer mechanisms.

The Processor shall ensure that appropriate safeguards are in place before any transfer of Personal Data outside the EU/EEA.

## 6. Audits

The Controller has the right to:
- Request evidence of the Processor's compliance with this DPA (e.g., security certifications, audit reports, questionnaire responses).
- Conduct or commission an audit of the Processor's data processing activities, with reasonable advance notice (at least 30 days) and during normal business hours.
- Audit costs are borne by the Controller unless the audit reveals material non-compliance by the Processor.

The Processor shall cooperate with audits and provide reasonable access to relevant information, systems, and personnel.

## 7. Liability

Liability under this DPA is governed by the limitation of liability provisions in the ToS, except that:
- Neither party limits its liability for breaches of GDPR that cannot be limited under applicable law.
- Each party is liable for damage caused by processing that infringes GDPR, in accordance with GDPR Article 82.

## 8. Term and Termination

This DPA enters into force upon execution by both parties and remains in effect for the duration of the Controller's use of the Service. It automatically terminates when all Personal Data has been deleted or returned in accordance with Section 4.8.

Provisions that by their nature should survive termination (including Sections 4.6, 4.8, 6, and 7) shall survive.

## 9. Governing Law

This DPA is governed by the laws of the Czech Republic. Disputes shall be resolved in accordance with the dispute resolution provisions of the ToS.

---

## Signatures

**Data Controller:**

Name: ___________________________
Title: ___________________________
Date: ___________________________
Signature: ___________________________

**Data Processor:**

Name: Marek Čermák
Title: Licensor, Engramia
Date: ___________________________
Signature: ___________________________
