# Engramia — Key Legal & Licensing Design Decisions

> This document captures key decisions from the licensing consultation (2026-03-23).
> It serves as a reference for future legal steps.

---

## 1. License

### Decision: BSL 1.1 → Apache 2.0

| Parameter | Value |
|-----------|-------|
| License | Business Source License 1.1 |
| Change Date | 4 years from each release |
| Change License | Apache 2.0 (patent grant + retaliation) |
| Additional Use Grant | Non-commercial (eval, test, dev, academic research) |
| SDK plugins (sdk/) | Consider Apache 2.0 separately (for framework compatibility) |

### Why BSL 1.1
- Code is publicly readable (reference, trust, prior art)
- Commercial/production use = paid license
- Prohibits competing SaaS without a license
- Strong precedent (HashiCorp → IBM acquisition $5.7B, MariaDB, CockroachDB)
- Converts to Apache 2.0 after 4 years

### Why Apache 2.0 as Change License (not MIT)
- Explicit patent grant — protects users
- Patent retaliation clause — deters patent trolls
- Code publication = prior art
- Compatible with everything relevant (LangChain MIT, CrewAI, etc.)

---

## 2. Trademark

### Q&A (2026-03-23)

**T1) Legal entity:**
Currently a sole trader (individual). Trade license — needs to be verified whether it is active.

**T2) Product name:**
A name other than "Engramia" is being considered — working proposal: "vAI.be" or similar.
Reason: "Engramia" is generic in the AI context, weaker protectability.

**T3) Trademark territory:**
Not ready to pay for registration yet. Wants to preserve the option to register in the future.

**T4) Logo:**
Does not exist yet — depends on the final name.

**T5) Name uniqueness:**
See T2 — looking for a more unique alternative.

---

## 3. Terms of Service

### Q&A (2026-03-23)

**S1) Hosting:**
Not resolved yet. Adoption-focused recommendation needed.

**S2) Sensitive user data:**
May store sensitive data. Position: disclaimer in ToS that the Licensor is not responsible for it.
Special conditions (DPA, GDPR compliance) = on-demand, paid add-on.

**S3) SLA (uptime guarantee):**
None currently. Consider for higher tiers.

**S4) Data after subscription ends:**
- Deletion after X days
- Free export while subscription is active + 30-day grace period
- After expiry: export for extra cost, then deletion

**S5) Use of data to improve the product:**
Yes — must be stated explicitly in ToS (aggregated metrics, anonymized patterns).

**S6) Pricing model:**
Monthly subscription + annual subscription + pay-as-you-go. A combination of all three.

**S7) Liability limitation:**
No liability for damages whatsoever. Guarantees = special enterprise agreement.

**S8) Trial:**
Yes, but genuinely limited to evaluation only. Details to be specified later.

**S9) Jurisdiction:**
Global — primarily developed countries where AI is actively used.

**S10) B2B vs B2C:**
Both. Note: B2C in the EU has stricter rules (consumer protection).

**S11) EU AI Act:**
Not considered yet. Will be reviewed separately.

**S12) Liability for Brain outputs:**
Borne by the customer. ToS must explicitly state that outputs are "informational".

---

## 4. Contributors

### Decision: No external contributors

- No CLA required
- No CONTRIBUTING.md
- Clean IP chain (single author) — ideal for acquisition
- License can be changed at any time without third-party consent

---

## 5. Name research (2026-03-23)

All considered names are taken:
- **vaibe** / **vaibe.com** — gamification SaaS platform
- **vaibe.ai** — Czech AI company, had to rename to Dazbog.ai (trademark conflict!)
- **vai.be** — Belgian ccTLD, likely taken
- **brayn.ai** — multiple existing projects (LinkedIn, brayn.app, brayneai.com)
- **memori.ai** — Italian AI platform (since 2017)
- **synaps.ai** — HR/recruitment AI
- **engram** — heavily taken (5+ companies/projects)
- **agent brain** — generic term, many GitHub projects

**Recommendation:** Look for a neologism (coined word), not a descriptive name.

## 6. ToS key decisions (2026-03-23)

| Item | Decision |
|------|----------|
| Hosting | EU (Frankfurt/Amsterdam) recommended — GDPR compliance default |
| Sensitive data | Disclaimer in ToS + Privacy Policy mandatory |
| SLA | None — "commercially reasonable efforts", enterprise SLA = paid add-on |
| Data after termination | 30-day grace period, export for cost, then deletion |
| Use of data | Yes (aggregated, anonymized) — must be stated explicitly in ToS |
| Pricing model | Monthly + annual (15–20% discount) + PAYG (higher unit price) |
| Liability | B2B: full exclusion. B2C EU: statutory minimum (cannot be excluded) |
| Jurisdiction | Governing law: Czech Republic, arbitration clause for international disputes |
| B2C in EU | 14-day withdrawal right, consumer warranties — consider self-service |
| Outputs | "Informational outputs" — liability on the customer |

## 7. Legal documents — status

| # | Document | Status | File |
|---|----------|--------|------|
| 1 | LICENSE (BSL 1.1) | ✅ Done | `LICENSE.txt` |
| 2 | Terms of Service | ✅ Draft | `docs/legal/TERMS_OF_SERVICE.md` |
| 3 | Privacy Policy | ✅ Draft | `docs/legal/PRIVACY_POLICY.md` |
| 4 | Cookie Policy | ✅ Draft | `docs/legal/COOKIE_POLICY.md` |
| 5 | DPA Template | ✅ Draft | `docs/legal/DPA_TEMPLATE.md` |
| 6 | EU AI Act analysis | ✅ Done | Result: minimal/limited risk, clause in ToS |
| 7 | Key Design Decisions | ✅ Done | `docs/legal/key-design-decisions.md` |

All drafts require legal review before commercial deployment (Phase 4.6.2.1).

## 8. Open questions

- [ ] Verify active trade license
- [x] Final product name — Engramia
- [x] Hosting provider and location for Cloud tier — Hetzner (Nuremberg)
- [ ] Trial model — detailed design. Goal: prevent unlimited use of the monthly free window. Give a limit in the first month and reduce it over time. Also add IP checks to prevent easy circumvention via a new account/IP.
- [ ] Trademark registration — timing and territory (EUIPO recommended after first customer)
- [ ] Fill in `[to be added]` placeholders in all documents (email, pricing URL)
