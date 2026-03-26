# Remanence — Key Legal & Licensing Design Decisions

> Tento dokument zachycuje klíčová rozhodnutí z licenční konzultace (2026-03-23).
> Slouží jako reference pro budoucí právní kroky.

---

## 1. Licence

### Rozhodnutí: BSL 1.1 → Apache 2.0

| Parametr | Hodnota |
|----------|---------|
| Licence | Business Source License 1.1 |
| Change Date | 4 roky od každého releasu |
| Change License | Apache 2.0 (patentový grant + retaliace) |
| Additional Use Grant | Non-production (eval, test, dev, academic research) |
| SDK pluginy (sdk/) | Zvážit Apache 2.0 separátně (pro kompatibilitu s frameworky) |

### Proč BSL 1.1
- Kód veřejně čitelný (reference, důvěra, prior art)
- Komerční/produkční použití = placená licence
- Zakazuje konkurenční SaaS bez licence
- Silný precedent (HashiCorp → IBM akvizice $5.7B, MariaDB, CockroachDB)
- Po 4 letech konverze na Apache 2.0

### Proč Apache 2.0 jako Change License (ne MIT)
- Explicitní patentový grant — chrání uživatele
- Patent retaliation clause — odrazuje patentové trolly
- Zveřejnění kódu = prior art
- Kompatibilní se vším relevantním (LangChain MIT, CrewAI, atd.)

---

## 2. Trademark (ochranná známka)

### Q&A (2026-03-23)

**T1) Právní entita:**
Zatím fyzická osoba. Živnost — nutno ověřit, zda je aktivní.

**T2) Název produktu:**
Zvažuje se jiný název než "Remanence" — pracovní návrh: "vAI.be" nebo podobné.
Důvod: "Remanence" je generický v AI kontextu, slabší ochranitelnost.

**T3) Území ochranné známky:**
Zatím nechce platit za registraci. Chce zajistit možnost registrace v budoucnu.

**T4) Logo:**
Zatím neexistuje — závisí na finálním názvu.

**T5) Unikátnost názvu:**
Viz T2 — hledá se unikátnější alternativa.

---

## 3. Terms of Service (obchodní podmínky)

### Q&A (2026-03-23)

**S1) Hosting:**
Zatím neřešeno. Doporučení z hlediska adopce potřeba.

**S2) Citlivá data uživatelů:**
Mohou ukládat citlivá data. Pozice: v ToS disclaimer, že za ně nezodpovídá.
Speciální podmínky (DPA, GDPR compliance) = on-demand, zpoplatněné.

**S3) SLA (garance dostupnosti):**
Aktuálně ne. Zvážit pro vyšší tiers.

**S4) Data po ukončení platby:**
- Smazání po X dnech
- Export zdarma jen dokud platí
- Po vypršení: export za extra cost, pak smazání

**S5) Použití dat ke zlepšení produktu:**
Ano — musí být explicitně v ToS (agregované metriky, anonymizované patterny).

**S6) Platební model:**
Měsíční předplatné + roční předplatné + pay-as-you-go. Kombinace.

**S7) Omezení odpovědnosti:**
Za škody neručí vůbec. Garance = speciální dohoda (enterprise).

**S8) Trial:**
Ano, ale omezený skutečně jen na vyzkoušení. Detaily budou upřesněny později.

**S9) Jurisdikce:**
Globálně — primárně vyspělé země kde se pracuje s AI.

**S10) B2B vs B2C:**
Obojí. Pozor: B2C v EU má přísnější pravidla (spotřebitelská ochrana).

**S11) EU AI Act:**
Dosud nezváženo. Projde se samostatně.

**S12) Odpovědnost za výstupy Brain:**
Nese zákazník. ToS musí explicitně uvádět, že výstupy jsou "informational".

---

## 4. Přispěvatelé

### Rozhodnutí: Žádní externí přispěvatelé

- Žádné CLA potřeba
- Žádné CONTRIBUTING.md
- Čistá IP chain (jediný autor) — ideální pro akvizici
- Licence lze kdykoli změnit bez souhlasu třetích stran

---

## 5. Průzkum názvů (2026-03-23)

Všechny zvažované názvy jsou obsazené:
- **vaibe** / **vaibe.com** — gamification SaaS platforma
- **vaibe.ai** — česká AI firma, musela se přejmenovat na Dazbog.ai (trademark konflikt!)
- **vai.be** — belgický ccTLD, pravděpodobně zabrané
- **brayn.ai** — více existujících projektů (LinkedIn, brayn.app, brayneai.com)
- **memori.ai** — italská AI platforma (od 2017)
- **synaps.ai** — HR/recruitment AI
- **engram** — silně obsazeno (5+ firem/projektů)
- **agent brain** — generický pojem, mnoho GitHub projektů

**Doporučení:** Hledat neologismus (vymyšlené slovo), ne deskriptivní název.

## 6. ToS klíčová rozhodnutí (2026-03-23)

| Bod | Rozhodnutí |
|-----|-----------|
| Hosting | EU (Frankfurt/Amsterdam) doporučeno — GDPR compliance default |
| Citlivá data | Disclaimer v ToS + Privacy Policy povinná |
| SLA | Žádné — "commercially reasonable efforts", enterprise SLA = placený add-on |
| Data po ukončení | 30 dnů grace period, export za cost, pak smazání |
| Použití dat | Ano (agregované, anonymizované) — musí být explicitně v ToS |
| Platební model | Měsíční + roční (sleva 15–20%) + PAYG (vyšší unit price) |
| Odpovědnost | B2B: plné vyloučení. B2C EU: zákonné minimum (nelze vyloučit) |
| Jurisdikce | Rozhodné právo ČR, arbitrážní doložka pro mezinárodní spory |
| B2C v EU | 14 dnů odstoupení, spotřebitelské záruky — zvážit samoobsluhu |
| Výstupy | "Informational outputs" — odpovědnost na zákazníkovi |

## 7. Právní dokumenty — stav

| # | Dokument | Stav | Soubor |
|---|----------|------|--------|
| 1 | LICENSE (BSL 1.1) | ✅ Hotovo | `LICENSE.md` |
| 2 | Terms of Service | ✅ Draft | `docs/legal/TERMS_OF_SERVICE.md` |
| 3 | Privacy Policy | ✅ Draft | `docs/legal/PRIVACY_POLICY.md` |
| 4 | Cookie Policy | ✅ Draft | `docs/legal/COOKIE_POLICY.md` |
| 5 | DPA Template | ✅ Draft | `docs/legal/DPA_TEMPLATE.md` |
| 6 | EU AI Act analýza | ✅ Hotovo | Výsledek: minimal/limited risk, klauzule v ToS |
| 7 | Key Design Decisions | ✅ Hotovo | `docs/legal/key-design-decisions.md` |

Všechny drafty vyžadují právní review před komerčním nasazením (Fáze 4.6.2.1).

## 8. Otevřené otázky

- [ ] Ověřit aktivní živnost
- [ ] Finální název produktu — hledat neologismus
- [ ] Hosting provider a lokace pro Cloud tier
- [ ] Trial model — detailní design
- [ ] Trademark registrace — timing a území (EUIPO doporučeno po prvním zákazníkovi)
- [ ] Doplnit placeholdery `[to be added]` ve všech dokumentech (email, pricing URL)
