# Acceptable Use Policy

**Engramia — Reusable Execution Memory for AI Agents**

Last updated: 2026-04-09

---

This Acceptable Use Policy ("AUP") governs your use of the Engramia Service
and Software. It supplements the [Terms of Service](TERMS_OF_SERVICE.md) and
applies to all users, including free-tier, trial, and paid subscribers.

Violation of this AUP may result in suspension or termination of your access
without prior notice. The Licensor reserves the right to update this policy
at any time; material changes will be communicated via email or in-product
notice at least 14 days in advance.

---

## 1. Prohibited Content

You may not use the Service to store, process, or transmit:

1. **Illegal content** — material that violates applicable law in the Czech
   Republic, the European Union, or the jurisdiction where you operate.
2. **Child sexual abuse material (CSAM)** — any content depicting or promoting
   the sexual exploitation of minors, in any form.
3. **Non-consensual intimate imagery** — intimate images or deepfakes of any
   person created or distributed without their consent.
4. **Incitement to violence** — content that directly incites, promotes, or
   glorifies violence against individuals or groups.
5. **Regulated personal data without authorization** — health records (HIPAA),
   financial records (PCI DSS), or other special-category data (GDPR Art. 9)
   unless you have obtained all required legal bases and have a valid DPA in
   place with Engramia.

## 2. Prohibited Activities

You may not:

1. **Circumvent access controls** — share API keys, bypass authentication,
   exploit vulnerabilities, or attempt to access other tenants' data.
2. **Reverse-engineer the Service** — decompile, disassemble, or extract
   algorithms, models, or trade secrets, except to the extent expressly
   permitted by applicable law (e.g., EU Directive 2009/24/EC Art. 6).
3. **Abuse system resources** — send requests designed to degrade service
   performance (DDoS, resource exhaustion), mine cryptocurrency, or consume
   compute disproportionate to legitimate use.
4. **Scrape or benchmark competitively** — systematically extract data or
   performance metrics for the purpose of developing, training, or marketing
   a competing product, except to the extent permitted by applicable law.
5. **Resell without authorization** — resell, sublicense, or rebrand the
   Service as your own product without a written reseller agreement.
6. **Automate account creation** — create accounts programmatically or use
   bots to register, except through officially provided APIs.

## 3. Prohibited AI Use Cases

In compliance with the EU AI Act (Regulation (EU) 2024/1689), you may not
use the Service in connection with AI systems that:

1. Deploy **subliminal, manipulative, or deceptive techniques** to distort
   behavior in ways that cause or are likely to cause significant harm.
2. Exploit **vulnerabilities of specific groups** (age, disability, social
   or economic situation) to materially distort behavior.
3. Perform **social scoring** — evaluating or classifying individuals based
   on social behavior or personal characteristics for detrimental treatment
   unrelated to the original context.
4. Perform **real-time remote biometric identification** in publicly
   accessible spaces for law enforcement, except where explicitly authorized
   by law.
5. Perform **emotion recognition** in workplaces or educational institutions,
   except for medical or safety purposes where permitted by law.
6. Create or maintain **facial recognition databases** through untargeted
   scraping of images from the internet or CCTV.

## 4. Fair Use and Rate Limits

- Respect published rate limits and quota allocations for your plan.
- Do not programmatically retry failed requests in tight loops without
  exponential backoff (minimum 1-second base delay).
- Do not use multiple accounts to circumvent per-account limits.
- Batch operations should be spread over reasonable time windows; sustained
  bursts exceeding 10x your plan's per-second limit may be throttled.

## 5. Data Responsibility

- **You are the data controller** for any personal data you store in
  Engramia. You are responsible for having a valid legal basis (GDPR Art. 6)
  and for responding to data subject requests.
- **PII redaction** is enabled by default (`ENGRAMIA_REDACTION=true`), but
  it is a best-effort heuristic. You must not rely on it as your sole
  compliance mechanism.
- **Do not store raw credentials** (passwords, private keys, tokens) in
  pattern content. Use references or hashes instead.

## 6. Reporting Violations

If you become aware of any use of the Service that violates this policy,
please report it to [security@engramia.dev](mailto:security@engramia.dev).

Reports are handled confidentially. We will not retaliate against good-faith
reporters.

## 7. Enforcement

Upon detecting or receiving a credible report of a violation, the Licensor
may, at its sole discretion:

1. Issue a warning with a deadline to cure the violation.
2. Temporarily suspend the offending tenant or API key.
3. Permanently terminate access without refund.
4. Report the activity to law enforcement if required by law.

Enforcement decisions are guided by severity, intent, and prior history.
The Licensor aims to warn before suspending, except for clear-cut illegal
activity (Section 1, items 1–4) or active exploitation of security
vulnerabilities (Section 2, item 1), where immediate action may be taken.

## 8. Relationship to Other Documents

| Document | Scope |
|----------|-------|
| [Terms of Service](TERMS_OF_SERVICE.md) | Contractual agreement governing Service use |
| This AUP | Behavioral rules for acceptable use |
| [Privacy Policy](PRIVACY_POLICY.md) | How we process your personal data |
| [DPA Template](DPA_TEMPLATE.md) | Data processing agreement for GDPR compliance |

In case of conflict between this AUP and the Terms of Service, the Terms
of Service shall prevail.

---

Contact: [legal@engramia.dev](mailto:legal@engramia.dev)
