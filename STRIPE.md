# Stripe Setup Guide — Engramia

Kompletní návod na konfiguraci Stripe pro Engramia cloud (SaaS). Odpovídá kódu v `engramia/billing/`.

---

## 1. Registrace a onboarding

Na [dashboard.stripe.com](https://dashboard.stripe.com/register) vytvořte účet a při onboardingovém průvodci zaškrtněte:

- **Recurring payments** — předplatné (Pro, Team)
- **Usage-based billing** — overage položky na faktuře (Pro: $5/500 runs, Team: $25/5 000 runs)
- **Tax collection** → **Flat rate** — Stripe Tax s automatickým výpočtem DPH
- **Prebuilt checkout form** — Stripe-hosted Checkout Session (mode: subscription)

---

## 2. API klíče

**Dashboard → Developers → API keys**

| Klíč | Popis | Env variable |
|---|---|---|
| Secret key (`sk_test_…`) | Backend — nikdy nezveřejňovat | `STRIPE_SECRET_KEY` |
| Publishable key (`pk_test_…`) | Frontend — lze zveřejnit | (frontend proměnná, není v backendu) |

Vložte do `.env` (nebo do secrets manageru v produkci):

```env
STRIPE_SECRET_KEY=sk_test_…
STRIPE_WEBHOOK_SECRET=whsec_…   # viz sekce 4
```

Bez těchto proměnných běží billing v **no-op módu** — API nevyhodí chybu, ale platby nejsou zpracovávány.

---

## 3. Produkty a ceny

**Dashboard → Product catalog → + Add product**

Vytvořte následující produkty a Price objekty. Každé `price_id` vygenerované Stripem vložte do frontendu (soubor `website/website/src/content/pricing.ts` — hodnoty `ctaHref`).

### Sandbox — $0/month

Sandbox je výchozí free tier pro všechny nové tenanty. **Žádný Stripe produkt ani Price objekt není potřeba** — tenant dostane sandbox automaticky při registraci bez platební metody.

### Pro — $29/month · $23/month yearly

| Pole | Hodnota |
|---|---|
| Product name | Engramia Pro |
| Description | Commercial plan for individuals and small teams |
| Pricing model | Standard pricing |
| Price (monthly) | **$29.00 USD** / month → recurring |
| Price (yearly) | **$276.00 USD** / year → recurring ($23/mo ekvivalent) |
| Billing period | Monthly / Yearly (dva samostatné Price objekty) |

Výsledek: **2 price_id** (např. `price_pro_monthly`, `price_pro_yearly`).

Overage se přidává dynamicky přes `stripe.InvoiceItem.create()` na event `invoice.created` — **žádný extra Price objekt** pro overage není potřeba.

### Team — $99/month · $79/month yearly

| Pole | Hodnota |
|---|---|
| Product name | Engramia Team |
| Description | Capacity, governance, and async processing for production teams |
| Pricing model | Standard pricing |
| Price (monthly) | **$99.00 USD** / month → recurring |
| Price (yearly) | **$948.00 USD** / year → recurring ($79/mo ekvivalent) |
| Billing period | Monthly / Yearly (dva samostatné Price objekty) |

Výsledek: **2 price_id** (např. `price_team_monthly`, `price_team_yearly`).

### Enterprise — Custom

Enterprise zákazníci kontaktují sales (`sales@engramia.dev`). **Žádný veřejný Stripe Price objekt** — předplatné se zakládá manuálně nebo přes Stripe Quotes.

### Přehled Price objektů

| Tier | Billing | price_id (příklad) |
|---|---|---|
| Pro | Monthly | `price_…` |
| Pro | Yearly | `price_…` |
| Team | Monthly | `price_…` |
| Team | Yearly | `price_…` |

Celkem **4 Price objekty**. ID zkopírujte do frontendu jako parametr `ctaHref` nebo do konfigurace.

---

## 4. Webhook endpoint

### Registrace v Dashboardu

**Dashboard → Developers → Webhooks → + Add endpoint**

| Pole | Hodnota |
|---|---|
| Endpoint URL | `https://api.engramia.dev/v1/billing/webhook` |
| Listen to | Events on your account |

**Events to send** — vyberte přesně tato:

| Event | Důvod |
|---|---|
| `customer.subscription.created` | Uloží nové předplatné do DB |
| `customer.subscription.updated` | Synchronizuje změnu plánu nebo stavu |
| `customer.subscription.deleted` | Downgrade na Sandbox, status → canceled |
| `invoice.paid` | Status → active, vymaže past_due_since |
| `invoice.payment_failed` | Status → past_due, spustí dunning grace period (7 dní) |
| `invoice.created` | Vloží overage InvoiceItem před finalizací faktury |

Po uložení zkopírujte **Signing secret** (`whsec_…`) do:

```env
STRIPE_WEBHOOK_SECRET=whsec_…
```

Backend ověřuje signaturu pomocí `stripe.Webhook.construct_event()` (HMAC-SHA256). Požadavky bez platné signatury jsou odmítnuty s HTTP 400.

Webhooky jsou idempotentní — duplicitní `stripe_event_id` jsou ignorovány (tabulka `processed_webhook_events`).

### Lokální vývoj

Nainstalujte [Stripe CLI](https://stripe.com/docs/stripe-cli) a spusťte:

```bash
stripe listen --forward-to localhost:8000/v1/billing/webhook
```

CLI vytiskne dočasný `whsec_…` — vložte ho do `.env` pro lokální session. Webhooku lze testovat:

```bash
stripe trigger customer.subscription.created
stripe trigger invoice.payment_failed
```

---

## 5. Customer Portal

**Dashboard → Settings → Billing → Customer portal → Activate**

Doporučená konfigurace:

- **Invoice history** — Enabled
- **Update subscriptions** — Allow customers to switch plans
- **Cancel subscriptions** — Enabled (at end of billing period)
- **Update payment methods** — Enabled

Kód volá `stripe.billing_portal.Session.create(customer=..., return_url=...)` bez custom `configuration` ID — použije se tato výchozí konfigurace.

---

## 6. Stripe Tax

**Dashboard → Settings → Tax → Enable Stripe Tax**

1. Přidejte **registraci CZ** (Czech Republic, EU OSS nebo standardní DPH):
   - Pokud sídlíte v ČR a prodáváte do EU → registrujte se na **OSS** (One Stop Shop) na [Finanční správě ČR](https://www.financnisprava.cz/cs/dane/mezinarodni-zdanovani/jedine-misto-registrace-oss).
   - Sazba DPH: 21 % (standardní CZ) / 0 % pro B2B reverse-charge v EU.
2. Nastavte **Origin address** (sídlo firmy).
3. Checkout Session má `automatic_tax: {enabled: true}` — Stripe vypočítá DPH automaticky.
4. `tax_id_collection: {enabled: true}` — B2B zákazníci mohou zadat VAT ID pro reverse-charge.

---

## 7. Smart Retries (Dunning)

**Dashboard → Settings → Billing → Subscriptions → Manage failed payments**

Doporučené nastavení odpovídající 7denní grace period v kódu (`past_due_since`):

| Nastavení | Hodnota |
|---|---|
| Retry schedule | Smart Retries — **4 pokusy** |
| Retry days | Den 3 → Den 5 → Den 7 → Den 14 |
| After all retries fail | **Cancel the subscription** |
| Send emails | Enabled (Stripe výchozí šablony) |

Tok při selhání platby:
1. `invoice.payment_failed` → backend nastaví `past_due_since`, grace period 7 dní
2. Stripe opakuje platbu (Smart Retries)
3. `invoice.paid` → backend nastaví `status = active`, vymaže `past_due_since`
4. Po 14 dnech bez platby → `customer.subscription.deleted` → backend downgraduje na Sandbox

---

## 8. Testovací karty

Použijte v **Test módu** (přepínač vlevo nahoře v dashboardu).

| Číslo karty | Chování |
|---|---|
| `4242 4242 4242 4242` | Úspěšná platba |
| `4000 0000 0000 0002` | Karta zamítnuta (`card_declined`) |
| `4000 0027 6000 3184` | Vyžaduje 3D Secure (SCA) |

Expiry: libovolné budoucí datum (např. `12/34`). CVV: libovolné 3 číslice.

---

## 9. Přechod do produkce

1. **Dashboard → přepnout Test → Live** (přepínač vlevo nahoře)
2. Zopakujte **krok 2** — zkopírujte **Live** secret key (`sk_live_…`) do produkčního `.env` / secrets manageru
3. Zopakujte **krok 3** — vytvořte produkty a Price objekty v Live módu (Test objekty se nepřenáší)
4. Zopakujte **krok 4** — zaregistrujte webhook endpoint s Live signing secret (`whsec_…`)
5. Zopakujte **krok 5** — aktivujte Customer Portal v Live módu
6. Ověřte Stripe Tax registrace v Live módu (krok 6)

> **Nikdy nepoužívejte `sk_test_…` v produkci ani `sk_live_…` v lokálním vývoji.**

---

## Přehled env variables

| Variable | Popis | Povinná |
|---|---|---|
| `STRIPE_SECRET_KEY` | Stripe secret API key (`sk_test_…` / `sk_live_…`) | Ano |
| `STRIPE_WEBHOOK_SECRET` | Webhook signing secret (`whsec_…`) | Ano |

Bez obou proměnných běží backend v no-op billing módu (Sandbox pro všechny).
