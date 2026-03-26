# Engramia — Weekly Audit Prompt

> Tento prompt slouží jako základ pro pravidelný týdenní audit projektu Engramia.
> Spouštěj ho v čistém kontextu (nová konverzace) s přístupem ke kompletnímu repozitáři.
> Výstupem je strukturovaný report s hodnocením, nálezy a action items.

---

## Instrukce pro auditora

Proveď kompletní audit projektu Engramia. Projdi **každou sekci** níže, u každé uveď:

- **Hodnocení**: ✅ OK | ⚠️ Varování | ❌ Problém | ℹ️ Info
- **Nálezy**: Co konkrétně jsi zjistil (s odkazem na soubor:řádek)
- **Action items**: Co je potřeba opravit/zlepšit (seřazeno dle priority)

Na konci vytvoř **Executive Summary** s celkovým skóre (0–100) a top 5 prioritami.

---

## 1. SECURITY AUDIT

### 1.1 Autentizace a autorizace
- Ověř, že `auth.py` stále používá `hmac.compare_digest()` pro timing-safe porovnání tokenů
- Zkontroluj, že dev mode (prázdný `ENGRAMIA_API_KEYS`) **není** náhodou aktivní v Docker produkčním nastavení
- Ověř, že API klíče nejsou nikde hardcodované ani v testech commitnuté jako reálné hodnoty
- Zkontroluj, zda neexistují endpointy, které obcházejí auth middleware

### 1.2 Input validace
- Projdi `schemas.py` — mají **všechna** string pole `max_length`?
- Ověř `eval_score` bounds [0, 10] v `brain.py` i v `schemas.py` (obě místa musí validovat)
- Zkontroluj `num_evals` cap (≤10) — funguje i na API vrstvě, ne jen v Brain?
- Hledej jakýkoli vstup od uživatele, který projde bez validace přímo do storage/LLM

### 1.3 Injection útoky
- **SQL injection**: Ověř, že všechny dotazy v `postgres.py` používají parametrizované queries (žádné f-stringy/string concatenation v SQL)
- **LIKE injection**: Ověř escapování `%` a `_` v PostgreSQL LIKE queries
- **Prompt injection**: Zkontroluj, že VŠECHNY LLM prompty v `composer.py`, `evaluator.py`, `prompt_evolver.py` a `failure_cluster.py` používají XML delimitery kolem uživatelského vstupu
- **Path traversal**: Ověř, že pattern keys v `delete_pattern`, `export`, `import_data` odmítají `..` a vyžadují prefix `patterns/`
- **Command injection**: Zkontroluj, zda CLI (`cli/main.py`) nepředává uživatelský vstup do `subprocess` nebo `os.system`

### 1.4 Rate limiting a DoS ochrana
- Ověř, že rate limiter v `middleware.py` správně počítá okna a provádí GC
- Zkontroluj, zda expensive endpointy (`/evaluate`, `/compose`, `/evolve`) mají nižší limit
- Ověř, že `BodySizeLimitMiddleware` kontroluje `Content-Length` a odmítá příliš velké requesty
- Hledej potenciální DoS vektory: může útočník spustit neomezeně LLM volání? Může vytvořit neomezeně patternů?

### 1.5 Security headers a CORS
- Ověř, že `SecurityHeadersMiddleware` přidává všechny headery (nosniff, DENY, no-referrer)
- Zkontroluj, že CORS je defaultně vypnutý a `ENGRAMIA_CORS_ORIGINS` vyžaduje explicitní konfiguraci
- Hledej endpointy, které vracejí interní detaily v chybových odpovědích (stack traces, file paths)

### 1.6 Audit logging
- Ověř, že `audit.py` loguje všechny security events: AUTH_FAILURE, PATTERN_DELETED, RATE_LIMITED
- Zkontroluj, zda audit logy obsahují dostatečný kontext (IP, timestamp, reason, pattern_key)
- Hledej security-relevantní akce, které NEJSOU logovány (např. bulk import, config changes)

### 1.7 Kryptografie a secrets
- Ověř SHA-256 pro key generation (žádné MD5 v produkčním kódu)
- Zkontroluj, zda `.gitignore` správně vylučuje `.env`, `*.key`, `*.pem`, credentials
- Hledej hardcodované secrets, API klíče, hesla v celém repozitáři (včetně testů a configů)

### 1.8 Docker security
- Ověř non-root user v Dockerfile (UID 1001, no shell)
- Zkontroluj, že `.dockerignore` vylučuje `.git`, `tests/`, `.env`
- Ověř, že base image je pinnutý na konkrétní verzi (ne `latest`)
- Zkontroluj, že Docker compose neexponuje interní porty zbytečně

---

## 2. TEST QUALITY AUDIT (ne jen coverage — skutečná kvalita)

### 2.1 Detekce falešné coverage
Pro každý testovací soubor zkontroluj:
- **Testují testy skutečné chování**, nebo jen volají funkce bez asercí?
- Existují testy, které `assert True` nebo `assert result is not None` bez ověření obsahu?
- Jsou mock objekty nakonfigurovány tak, že **vždy vrací úspěch** a nikdy netestují chybové stavy?
- Prochází testy i při fundamentálně rozbitém kódu? (= testy nic netestují)

### 2.2 Coverage vs. skutečná pokrytost
- Spusť `pytest --cov=engramia --cov-report=term-missing` a analyzuj **MISSING řádky**
- Pro moduly pod 50% coverage (`providers/openai.py`, `providers/postgres.py`, `reuse/contracts.py`, `sdk/*`) — je nízká coverage přijatelná (vyžaduje external service) nebo je to laziness?
- Existují **kritické code paths**, které nejsou testované? Zejména:
  - Error handling větve v `brain.py` (co se stane, když LLM provider selže?)
  - Edge cases v `success_patterns.py` (aging s 0 patterny, reuse boost na max)
  - Concurrency v `json_storage.py` (race conditions)
  - Pipeline validation v `contracts.py` (circular deps, empty reads/writes)

### 2.3 Test izolace a determinismus
- Závisí nějaké testy na pořadí spuštění? (spusť `pytest --randomly-seed=random` pokud je plugin dostupný)
- Sdílejí testy stav přes globální proměnné nebo shared fixtures?
- Jsou všechny tmp soubory vytvářeny přes `tmp_path` fixture (ne do working directory)?
- Závisí testy na aktuálním čase? (pattern aging) — jsou mockované?

### 2.4 Edge cases a negativní testy
- Existují testy pro prázdný vstup? (prázdný task, prázdný code)
- Existují testy pro extrémní hodnoty? (eval_score=0, eval_score=10, limit=0, limit=10000)
- Testují se chybové odpovědi API? (400, 401, 404, 413, 429, 500)
- Testuje se správné chování při chybějícím LLM provideru?
- Testuje se concurrent access k JSONStorage?

### 2.5 Integration a E2E testy
- Pokrývá `test_e2e.py` kompletní learn→recall→compose→evaluate cyklus?
- Testuje `test_integration.py` reálný feedback loop (learn → eval → feedback injection → lepší výsledky)?
- Jsou API testy v `test_api/` skutečné integrace (s Brain instancí), nebo jen unit testy routes?

---

## 3. FEATURE COMPLETENESS AUDIT

### 3.1 Core features vs. roadmap
Porovnej implementovaný stav s `roadmap.md`:
- Jsou všechny features označené jako ✅ Complete skutečně kompletní a funkční?
- Existují částečně implementované features, které nejsou v roadmapě označené?
- Jsou v kódu TODO/FIXME komentáře indikující nedokončenou práci?

### 3.2 Public API konzistence
- Odpovídá `__init__.py` export skutečnému public API? (žádné chybějící/přebytečné exporty)
- Má každá public metoda v `Brain` class docstring s parametry a return types?
- Jsou type hints kompletní na všech public API?
- Odpovídá REST API (`routes.py`) 1:1 Python API (`brain.py`)? Chybí nějaký endpoint?

### 3.3 Provider implementace
- Implementují `OpenAIProvider`, `AnthropicProvider` **všechny** metody z `LLMProvider` ABC?
- Implementují storage backendy **všechny** metody z `StorageBackend` ABC?
- Funguje `LocalEmbeddings` jako plnohodnotná náhrada `OpenAIEmbeddings`?
- Je embedding dimenze konzistentní mezi providery? (OpenAI=1536, local=384 — jak to řeší storage?)

### 3.4 SDK integrace
- Funguje `LangChainCallback` s aktuální verzí `langchain-core`? (zkontroluj kompatibilitu API)
- Je `WebhookClient` funkční proti reálnému Brain API? (zkontroluj URL paths, auth headers)
- Odpovídá CLI (`main.py`) dokumentovaným příkazům v README?

### 3.5 Data persistence a migrace
- Je export/import format (`brain.export()` / `brain.import_data()`) verzovaný?
- Funguje migrace mezi JSON a PostgreSQL storage?
- Jsou Alembic migrace up-to-date s aktuálními SQLAlchemy modely?

---

## 4. PRODUCTION READINESS AUDIT

### 4.1 Error handling a resilience
- Co se stane, když LLM provider timeout? (retry logika v `openai.py`, `anthropic.py`)
- Co se stane, když storage je plný nebo nedostupný?
- Co se stane při nevalidním JSON v storage souborech?
- Jsou všechny `except` bloky specifické (ne bare `except:` nebo `except Exception:`)?
- Escapují chybové odpovědi uživatelský vstup? (XSS v error messages)

### 4.2 Concurrency a thread safety
- Je `threading.Lock` v `json_storage.py` dostatečný? (co reader-writer pattern?)
- Je rate limiter v `middleware.py` thread-safe? (shared dict bez locku?)
- Co se stane při concurrent writes do stejného pattern?
- Funguje `ThreadPoolExecutor` v `evaluator.py` správně při vysoké zátěži?

### 4.3 Resource management
- Jsou HTTP spojení k LLM providerům správně zavírána?
- Existují memory leaky? (neomezený růst in-memory dat, rate limit counters bez GC)
- Je PostgreSQL connection pool správně nakonfigurován? (pool size, timeout, recycle)
- Co se stane, když JSON storage soubor naroste na stovky MB?

### 4.4 Logging a observability
- Používá každý modul `logging.getLogger(__name__)`? (žádné `print()`)
- Jsou logy na správných úrovních? (DEBUG pro detaily, INFO pro operace, WARNING pro anomálie, ERROR pro selhání)
- Obsahují logy dostatečný kontext pro debugging? (task_id, pattern_key, provider name)
- Nelogují se citlivá data? (API klíče, plný obsah uživatelských promptů)

### 4.5 Configuration management
- Jsou všechny env vars dokumentované v `docker-compose.yml` a `README.md`?
- Mají všechny env vars rozumné defaulty?
- Je konfigurace validována při startu? (ne až při prvním requestu)
- Existuje konfigurace, která může způsobit tichý fail? (např. špatný DATABASE_URL který se projeví až při prvním write)

### 4.6 Graceful degradation
- Funguje Brain bez LLM provideru? (recall/learn by měly, compose/evaluate ne)
- Funguje Brain bez embedding provideru? (degradace na keyword matching?)
- Co se stane, když pgvector extension není nainstalován v PostgreSQL?
- Jsou optional dependencies (`openai`, `anthropic`, `sentence-transformers`) skutečně optional? (lazy import check)

---

## 5. CODE QUALITY AUDIT

### 5.1 Architektura a design
- Dodržuje kód **single responsibility principle**? (není brain.py monolith s příliš mnoho odpovědností?)
- Je dependency injection konzistentní? (ne mix DI a globálních singletonů)
- Existují circular imports?
- Je public API stabilní? (breaking changes by měly být zdokumentované)

### 5.2 Kódové konvence
- Dodržuje kód konzistentní styl? (naming, indentation, import order)
- Jsou Pydantic modely v `types.py` a `schemas.py` konzistentní? (duplikace vs. reuse)
- Existuje dead code? (nepoužívané importy, funkce, proměnné)
- Jsou magic numbers nahrazeny konstantami?

### 5.3 Dependency health
- Jsou dependencies v `pyproject.toml` na aktuálních verzích?
- Existují known vulnerabilities v dependencies? (`pip audit` nebo ekvivalent)
- Jsou version ranges rozumné? (ne příliš volné `>=1.0` ani příliš striktní `==1.2.3`)
- Existují nepoužívané dependencies?

### 5.4 Dokumentace
- Odpovídá `README.md` aktuálnímu stavu kódu?
- Odpovídá `CLAUDE.md` aktuální architektuře? (soubory, moduly, features)
- Je `CHANGELOG.md` aktuální?
- Obsahuje `SECURITY.md` aktuální seznam known limitations?

---

## 6. DATA INTEGRITY AUDIT

### 6.1 Pattern storage
- Jak se zachází s duplicitními patterny? (same task + code = same key?)
- Je SHA-256 key generation deterministická a collision-resistant?
- Co se stane při corrupted JSON storage file?
- Funguje atomic write v `json_storage.py` spolehlivě? (write → rename)

### 6.2 Embedding consistency
- Jsou embeddingy přepočítávány při změně embedding modelu?
- Co se stane, když recall najde pattern s embedding z jiného modelu/dimenze?
- Je cosine similarity v JSON backendu numericky stabilní? (normalizace, zero vectors)

### 6.3 Aging a decay
- Je decay rate (2%/týden) korektně implementován? (compound vs. linear)
- Co se stane, když aging neběží dlouho? (masivní jednorázový drop?)
- Je pruning threshold správně nastavený? (kdy se pattern smaže úplně?)
- Funguje reuse boost (+0.1, max 10.0) správně s aging dohromady?

### 6.4 Eval feedback
- Je Jaccard clustering (>0.4 threshold) dostatečně přesný?
- Funguje feedback decay (10%/týden) nezávisle na pattern aging?
- Co se stane při tisících feedback entries? (performance, memory)

---

## 7. COMPLIANCE A LEGAL AUDIT

### 7.1 Licence
- Je BSL 1.1 licence správně aplikována? (LICENSE.txt, pyproject.toml header)
- Jsou všechny third-party dependencies kompatibilní s BSL 1.1?
- Obsahují zdrojové soubory licence header? (pokud je to konvence projektu)

### 7.2 Legal dokumenty
- Odpovídá `TERMS_OF_SERVICE.md` aktuální funkcionalitě?
- Je `PRIVACY_POLICY.md` konzistentní s tím, jaká data Brain skutečně zpracovává?
- Je `DPA_TEMPLATE.md` aktuální vůči GDPR požadavkům?

---

## 8. REGRESSION CHECK

### 8.1 Od minulého auditu
- Byly všechny action items z minulého auditu vyřešeny?
- Nezavedl nový kód regrese v oblastech, které byly dříve opraveny?
- Nezhoršila se coverage oproti minulému auditu?
- Přibyly nové TODO/FIXME komentáře?

### 8.2 Git history check
- Existují commity, které mění security-critical kód bez odpovídajícího testu?
- Existují revert commity indikující nestabilitu?
- Jsou commit messages konzistentní a informativní?

---

## VÝSTUPNÍ FORMÁT

### Executive Summary

```
Celkové skóre: XX/100
Datum auditu: YYYY-MM-DD
Auditovaná verze: vX.Y.Z (commit hash)

Top 5 priorit:
1. [❌/⚠️] Oblast — Popis problému — Dopad
2. ...
```

### Detailní tabulka

```
| # | Sekce | Hodnocení | Nálezy | Action Items |
|---|-------|-----------|--------|--------------|
| 1 | Security — Auth | ✅ | ... | ... |
| 2 | Security — Input | ⚠️ | ... | ... |
| ... | ... | ... | ... | ... |
```

### Metriky

```
Test coverage: XX%
Počet testů: XXX
Počet ❌ nálezů: X
Počet ⚠️ nálezů: X
Nové issues od minulého auditu: X
Vyřešené issues od minulého auditu: X
```

---

## POZNÁMKY K POUŽITÍ

1. **Frekvence**: 1x týdně, ideálně před merge do main
2. **Kontext**: Spouštěj v čisté konverzaci s kompletním přístupem k repozitáři
3. **Baseline**: První audit vytvoří baseline, další audity porovnávají s předchozím
4. **Prioritizace**: ❌ opravit ihned, ⚠️ opravit do příštího auditu, ℹ️ sledovat
5. **Rozsah**: Pokud se projekt výrazně rozroste, audit je možné rozdělit na 2 sessiony (Security+Tests | Features+Production+Quality)
6. **Aktualizace tohoto promptu**: Když přibude nový modul, nová feature nebo nový security concern — aktualizuj odpovídající sekci
