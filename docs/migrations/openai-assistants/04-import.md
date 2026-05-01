# 4. Bulk-import to Engramia

You have an NDJSON dump of OpenAI messages from [step 3](03-export-threads.md). This step writes them into Engramia as patterns under the correct scope.

!!! info "Why not /v1/import?"
    `POST /v1/import` is the **symmetric pair to `GET /v1/export`** — it expects round-tripped Engramia exports (`{version, key, data}` records). For a fresh-data migration like this one, use `Memory.learn()` (Python) or `POST /v1/learn` (REST) instead — one call per user/assistant message pair.

## Mapping decisions

You have to make three decisions before running the import:

### a) Which scope does each Thread land in?

Pick one of:

- **One project per assistant** — clean separation, easiest to reason about. Recommended if you had 3-10 distinct assistants.
- **One project per customer/tenant** — best if your assistants are customer-facing and you need GDPR-grade isolation.
- **One project total** — only if your assistants were internal and you want everything in one shared recall pool.

Set `ENGRAMIA_TENANT_ID` and `ENGRAMIA_PROJECT_ID` accordingly when running the importer. (Or pass them as `auth_context` if you're calling Engramia via REST.)

### b) What is `eval_score` for an imported message?

OpenAI doesn't tell you whether a past assistant message was good or bad. Three options:

| Strategy | Score | When |
|---|---|---|
| Neutral default | `5.0` | Default. Patterns are recallable but won't dominate fresh, evaluated runs. |
| Heuristic from feedback | `7.0` if you have positive UX signal (thumbs-up, accepted suggestion); `3.0` if negative | If you stored user feedback alongside thread_id. |
| Re-evaluate post-hoc | Run `memory.evaluate()` on each pair after import | Costs one LLM call per pattern. Most accurate. Skip on first pass. |

Default to neutral (`5.0`) on the first import. You can re-evaluate later with `engramia evaluate-imported` (CLI) once the new system is live.

### c) How are user/assistant pairs grouped into patterns?

Each Engramia pattern is `(task, code, eval_score)`. The natural grouping is:

```
user message     → pattern.task
next assistant   → pattern.code (or pattern.output)
message in same   eval_score = 5.0 (neutral)
thread
```

Multi-turn refinements (user, assistant, user, assistant) become **two patterns**, not one. This is intentional — recall ranks them independently.

## The import script

```python
# import_to_engramia.py — convert exported NDJSON into Engramia patterns
import json
import sys
from engramia import Memory

def pair_messages(records):
    """Group consecutive (user, assistant) pairs from one thread."""
    by_thread: dict[str, list] = {}
    for r in records:
        by_thread.setdefault(r["thread_id"], []).append(r)

    for tid, msgs in by_thread.items():
        msgs.sort(key=lambda r: r["created_at"])
        i = 0
        while i < len(msgs) - 1:
            if msgs[i]["role"] == "user" and msgs[i + 1]["role"] == "assistant":
                yield msgs[i], msgs[i + 1]
                i += 2
            else:
                i += 1

def main(ndjson_path: str):
    memory = Memory()  # picks up ENGRAMIA_* env vars

    with open(ndjson_path) as f:
        records = [json.loads(line) for line in f if line.strip()]

    pairs = list(pair_messages(records))
    print(f"Found {len(pairs)} (user, assistant) pairs across "
          f"{len({r['thread_id'] for r in records})} threads")

    imported = 0
    for user_msg, asst_msg in pairs:
        try:
            memory.learn(
                task=user_msg["text"][:2000],          # truncate to safety limit
                code=asst_msg["text"][:8000],
                eval_score=5.0,                        # neutral — see step (b)
                source="import",
                run_id=f"openai-thread:{user_msg['thread_id']}",
                on_duplicate="skip",                   # don't clobber later, evaluated patterns
            )
            imported += 1
        except Exception as exc:
            print(f"skip {user_msg['message_id']}: {exc}")

    print(f"Imported {imported}/{len(pairs)} patterns")

if __name__ == "__main__":
    main(sys.argv[1])
```

Run it:

```bash
export ENGRAMIA_TENANT_ID=t_abc
export ENGRAMIA_PROJECT_ID=p_main
python import_to_engramia.py threads.ndjson
```

## REST variant

If you don't run Python in your import host, the same logic over REST:

```bash
curl -X POST https://api.engramia.dev/v1/learn \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Build a CSV parser",
    "code": "import csv\n...",
    "eval_score": 5.0,
    "source": "import",
    "run_id": "openai-thread:thread_abc"
  }'
```

One request per pattern. Rate-limited at ~30 req/sec on hosted plans — for >50k patterns, prefer the Python path.

## Dedup

`on_duplicate="skip"` is recommended for backfills. Two reasons:

1. If you re-run the importer, you don't want it to overwrite patterns the new system has since evaluated and improved.
2. The Jaccard-0.92 dedup threshold catches near-duplicate user prompts ("build CSV parser" vs "build a CSV parser") — without it you'd accumulate noise.

## Verify

```bash
curl https://api.engramia.dev/v1/metrics \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

The response shows `pattern_count` for the current scope. Should match `imported` from the script (within the dedup tolerance).

## Next

[Tools & files mapping](05-tools-files.md) — what to do about `code_interpreter`, `file_search`, and your function-calling tools.
