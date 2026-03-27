# Integrace Engramia → Agent Factory V2

Tento dokument popisuje kroky pro zapojení Engramia Brain API do Agent Factory V2
jako testování paměťové vrstvy v reálném prostředí.

**Cíl:** Ověřit, že `learn` / `recall` / `feedback` fungují přes REST API
při skutečných factory runs, bez narušení stávající logiky.

**Strategie:** Additivní integrace — Engramia běží **paralelně** vedle existující
paměti factory (`memory/success_patterns.json`). Nic se nemazže, nic se nerozbije.

---

## Přehled integračních bodů

Agent Factory V2 main flow (`orchestrator/generation.py`):

| Místo v kódu | Řádek | Engramia akce |
|---|---|---|
| `add_success_pattern(task, design)` | ~219 | `POST /v1/learn` s task + design + eval_score |
| `find_reuse_candidate(task)` | ~154 | `POST /v1/recall` — obohacení kontextu pro architekta |
| `get_top_feedback_patterns()` (coder prompt) | coder.py | `GET /v1/feedback` — doplněk k lokální feedback DB |
| Periodicky (po N runech) | — | `POST /v1/aging` |

---

## Fáze 1 — Lokální test (bez VM, bez sítě)

Nejrychlejší cesta k prvnímu end-to-end testu. Engramia API běží lokálně
na `localhost:8000`, agent_factory_v2 volá na stejném stroji přes webhook SDK.

### 1.1 Spustit Engramia lokálně

```bash
# V adresáři agent-brain
docker compose up
# => API dostupné na http://localhost:8000/v1/health
```

Ověření:
```bash
curl http://localhost:8000/v1/health
# => {"status":"ok","storage":"json"}
```

### 1.2 Nainstalovat engramia do agent_factory_v2 venvu

```bash
# V adresáři agent_factory_v2, s aktivovaným venvem
pip install "engramia"
# nebo přímo ze zdrojů (pokud není na PyPI):
pip install -e C:\Users\soulf\agent-brain
```

Webhook SDK (`engramia.sdk.webhook`) nemá žádné extra závislosti (používá stdlib `urllib`).

### 1.3 Vytvořit bridge modul

Soubor: `agent_factory_v2/memory/engramia_bridge.py`

```python
"""engramia_bridge.py — Thin wrapper around EngramiaWebhook for Agent Factory V2.

Additive integration: calls Engramia in parallel with existing local memory.
All errors are silently caught so factory runs are never blocked by Brain API issues.
"""

import os
import logging

log = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    url = os.getenv("ENGRAMIA_URL", "").strip()
    if not url:
        return None

    try:
        from engramia.sdk.webhook import EngramiaWebhook
        api_key = os.getenv("ENGRAMIA_API_KEY", "")
        _client = EngramiaWebhook(url=url, api_key=api_key or None)
        log.info("[EngramiaBridge] Connected to %s", url)
    except Exception as e:
        log.debug("[EngramiaBridge] Init failed: %s", e)
        _client = None

    return _client


def learn(task: str, code: str, eval_score: float, design: dict | None = None) -> None:
    """Record a successful run into Engramia Brain."""
    client = _get_client()
    if client is None:
        return
    try:
        import json
        client.learn(
            task=task,
            code=code,
            eval_score=eval_score,
            output=json.dumps(design, default=str)[:500] if design else None,
        )
        log.debug("[EngramiaBridge] learn() OK  task=%s  score=%.1f", task[:60], eval_score)
    except Exception as e:
        log.debug("[EngramiaBridge] learn() failed: %s", e)


def recall(task: str, limit: int = 3) -> list[dict]:
    """Fetch relevant patterns from Engramia Brain. Returns [] on any error."""
    client = _get_client()
    if client is None:
        return []
    try:
        matches = client.recall(task=task, limit=limit)
        log.debug("[EngramiaBridge] recall() got %d matches for: %s", len(matches), task[:60])
        return matches
    except Exception as e:
        log.debug("[EngramiaBridge] recall() failed: %s", e)
        return []


def get_feedback(task_type: str | None = None, limit: int = 4) -> list[str]:
    """Fetch recurring quality feedback from Engramia Brain. Returns [] on any error."""
    client = _get_client()
    if client is None:
        return []
    try:
        return client.feedback(task_type=task_type, limit=limit)
    except Exception as e:
        log.debug("[EngramiaBridge] feedback() failed: %s", e)
        return []


def run_aging() -> None:
    """Trigger pattern aging in Engramia Brain."""
    client = _get_client()
    if client is None:
        return
    try:
        client.aging()
        log.debug("[EngramiaBridge] aging() OK")
    except Exception as e:
        log.debug("[EngramiaBridge] aging() failed: %s", e)
```

### 1.4 Přidat hook — learn po úspěšném runu

V souboru `orchestrator/generation.py`, za řádek s `add_success_pattern(task, design)` (~řádek 219):

```python
# Existing line (keep):
add_success_pattern(task, design)
record_success()

# ADD AFTER:
try:
    from memory.engramia_bridge import learn as engramia_learn
    _brain_score = eval_score if eval_score is not None else 7.0
    engramia_learn(task=task, code=code, eval_score=_brain_score, design=design)
except Exception as e:
    log.debug("[EngramiaBridge] learn hook failed: %s", e)
```

> `eval_score` je k dispozici až po evaluate_agent(), ale `add_success_pattern` je volán
> před tím (řádek 219) bez skóre. Přidej Engramia learn hook **za** blok s eval_score
> (za řádkem ~312 kde je `log_routing_entries`), aby se poslalo finální skóre.

### 1.5 Přidat hook — recall před code generation (volitelné pro MVP)

V souboru `orchestrator/generation.py`, za `find_reuse_candidate(task)` (~řádek 154):

```python
# After existing reuse candidate logic:
try:
    from memory.engramia_bridge import recall as engramia_recall
    _brain_matches = engramia_recall(task, limit=3)
    if _brain_matches:
        log.debug("[EngramiaBridge] %d patterns from Brain for context", len(_brain_matches))
        # Future: inject into architect context / coder prompt
except Exception as e:
    log.debug("[EngramiaBridge] recall hook failed: %s", e)
```

Inject do architect promptu (Phase 2 tohoto plánu) — pro MVP stačí zalogovat.

### 1.6 Nastavit env proměnné v agent_factory_v2

Do `.env` (nebo exportovat před spuštěním):

```bash
# Lokální Engramia (docker compose up v agent-brain)
ENGRAMIA_URL=http://localhost:8000
ENGRAMIA_API_KEY=          # prázdné = dev mode (bez auth)
```

### 1.7 Spustit test

```bash
# V agent_factory_v2:
python factory.py "Parse a CSV file and compute summary statistics"
# => mělo by proběhnout bez chyb
# => po úspěšném runu: zkontrolovat Engramia metriky

curl http://localhost:8000/v1/metrics
# => {"runs": 0, "pattern_count": 1, ...}

curl http://localhost:8000/v1/recall \
  -X POST -H "Content-Type: application/json" \
  -d '{"task": "CSV statistics", "limit": 3}'
# => vrátí pattern z předchozího runu
```

---

## Fáze 2 — Produkční test (Hetzner VM)

### 2.1 Zpřístupnit API na VM

**Problém:** Port 8000 je aktuálně zablokován Hetzner firewallem.
(`curl http://178.104.100.91:8000/v1/health` → Connection refused)

**Možnost A — Rychlý test (otevřít port 8000 přímo):**
1. V Hetzner Console → Firewall → přidat rule: `TCP 8000 inbound from 0.0.0.0/0`
2. Ověřit: `curl http://178.104.100.91:8000/v1/health`
3. Po otestování port zase zavřít (není vhodné pro produkci)

**Možnost B — Produkční způsob (Caddy + TLS, roadmap Phase 4.6.0):**
1. SSH na VM: `ssh user@178.104.100.91`
2. Nainstalovat Caddy:
   ```bash
   sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update && sudo apt install caddy
   ```
3. Vytvořit `/etc/caddy/Caddyfile`:
   ```
   api.engramia.dev {
       reverse_proxy localhost:8000
   }
   ```
4. `sudo systemctl reload caddy`
5. Ověřit: `curl https://api.engramia.dev/v1/health`

### 2.2 Ověřit / nastavit API klíče na VM

SSH na VM:
```bash
cd /path/to/deployment  # DEPLOY_PATH z GitHub Secrets
cat .env | grep ENGRAMIA_API_KEYS
```

Pokud je prázdné nebo `change-me-before-deployment`:
```bash
# Vygenerovat silný klíč:
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Přidat do .env:
ENGRAMIA_API_KEYS=<vygenerovaný-klíč>
# Restartovat container:
docker compose -f docker-compose.prod.yml up -d
```

### 2.3 Ověřit, že API container běží

```bash
docker ps | grep engramia
docker compose -f docker-compose.prod.yml logs --tail=20 engramia-api
```

Pokud container neběží (deploy proběhl přes GitHub Actions na poslední release):
```bash
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
```

### 2.4 Přepnout agent_factory na VM API

```bash
# V agent_factory_v2 .env:
ENGRAMIA_URL=http://178.104.100.91:8000       # Možnost A (port přímý)
# nebo:
ENGRAMIA_URL=https://api.engramia.dev         # Možnost B (Caddy + TLS)
ENGRAMIA_API_KEY=<klíč z VM .env>
```

### 2.5 Spustit factory run a ověřit flow

```bash
python factory.py "Fetch stock prices for AAPL and compute 7-day moving average"
# Po dokončení:
curl -H "Authorization: Bearer <api-key>" https://api.engramia.dev/v1/metrics
curl -H "Authorization: Bearer <api-key>" -X POST https://api.engramia.dev/v1/recall \
  -H "Content-Type: application/json" \
  -d '{"task": "AAPL moving average", "limit": 3}'
```

---

## Fáze 3 — Plná integrace (po ověření MVP)

Tato fáze rozšiřuje integraci o aktivní recall inject do promptů.
Realizovat až po úspěšném ověření Fáze 1+2.

### 3.1 Inject Engramia context do architect promptu

V `agents/architect.py`, v části kde se builduje system prompt:

```python
from memory.engramia_bridge import recall as engramia_recall

_brain_matches = engramia_recall(task, limit=3)
if _brain_matches:
    _brain_context = "\n".join(
        f"- {m['pattern']['task']}: {m['pattern']['design'][:200]}"
        for m in _brain_matches if m.get("pattern")
    )
    # Přidat do system promptu architekta jako sekci "PROVEN PATTERNS FROM BRAIN"
```

### 3.2 Inject Engramia feedback do coder promptu

V `agents/coder.py`, kde se volá `get_top_feedback_patterns()`:

```python
from memory.engramia_bridge import get_feedback as engramia_feedback

_brain_feedback = engramia_feedback(limit=4)
# Merge s lokálními feedback patterns, deduplicate
```

### 3.3 Periodický aging

V `orchestrator/session.py` → `startup_tasks()`:

```python
from memory.engramia_bridge import run_aging as engramia_aging
# Spustit jednou za N runů:
if _run_count % 50 == 0:
    engramia_aging()
```

---

## Checklist

### Lokální test
- [ ] `docker compose up` v agent-brain — API běží na localhost:8000
- [ ] `pip install engramia` v agent_factory_v2 venvu
- [ ] Vytvořit `memory/engramia_bridge.py`
- [ ] Přidat learn hook do `orchestrator/generation.py`
- [ ] Nastavit `ENGRAMIA_URL=http://localhost:8000` v agent_factory_v2 `.env`
- [ ] Spustit `python factory.py "test task"` — bez chyb
- [ ] Ověřit `GET /v1/metrics` → `pattern_count >= 1`
- [ ] Ověřit `POST /v1/recall` → vrátí pattern z factory runu

### Produkční test
- [ ] Zpřístupnit port (Hetzner firewall nebo Caddy)
- [ ] Ověřit `ENGRAMIA_API_KEYS` na VM
- [ ] Ověřit běžící container: `docker ps | grep engramia`
- [ ] Přepnout `ENGRAMIA_URL` na VM adresu
- [ ] Spustit 3–5 factory runů s různými tasky
- [ ] Ověřit recall — druhý run na podobný task by měl vrátit pattern z prvního

---

## Poznámky

- **Žádné breaking changes** — bridge modul zachytí všechny výjimky, factory nikdy nespadne kvůli Engramia
- **Embeddings** — Engramia potřebuje OpenAI API key pro generování embeddingů (`OPENAI_API_KEY` v prostředí kde běží Docker container)
- **Lokální embeddings** — alternativa bez API klíče: nastavit `ENGRAMIA_EMBEDDING_PROVIDER=local` (sentence-transformers, 384-dim, horší kvalita)
- **Docker prerekvizita** — Engramia lokálně běží v Dockeru, agent_factory_v2 ho volá přes HTTP — Docker tedy musí být spuštěný
