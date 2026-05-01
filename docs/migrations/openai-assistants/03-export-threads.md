# 3. Export Threads from OpenAI

To carry your existing Assistants conversation history into Engramia, first dump it from OpenAI to a flat NDJSON file. This step talks **only** to OpenAI — Engramia is not involved yet.

!!! warning "Time-sensitive"
    Run this **before** 26 August 2026. After the sunset, the Assistants API returns `410 Gone` and your message history is unrecoverable from this side.

## What you need

- The same `OPENAI_API_KEY` you used in production
- A list of `assistant_id`s you control (find them via `client.beta.assistants.list()`)
- A list of `thread_id`s — typically you have these in your application database. The OpenAI API does **not** let you enumerate all threads under your account.

!!! danger "OpenAI does not list threads for you"
    The Assistants API has no `/v1/threads` GET. You must already know the `thread_id`s — they are usually stored in your own database keyed by user/conversation. If you don't have them, message history for those threads is unrecoverable; you can only export forward-looking runs.

## The export script

```python
# export_threads.py — dump Assistants threads to NDJSON
import json
import sys
from openai import OpenAI

client = OpenAI()

def export_thread(thread_id: str, assistant_id: str):
    """Yield one record per message in the thread."""
    cursor = None
    while True:
        page = client.beta.threads.messages.list(
            thread_id=thread_id,
            order="asc",
            limit=100,
            after=cursor,
        )
        for msg in page.data:
            text_parts = [
                c.text.value for c in msg.content if c.type == "text"
            ]
            yield {
                "thread_id": thread_id,
                "assistant_id": assistant_id,
                "message_id": msg.id,
                "role": msg.role,           # "user" or "assistant"
                "text": "\n".join(text_parts),
                "created_at": msg.created_at,  # unix epoch
            }
        if not page.has_more:
            return
        cursor = page.data[-1].id

def main(thread_ids_file: str, assistant_id: str, out_path: str):
    """Read thread_ids one per line; write one NDJSON record per message."""
    with open(thread_ids_file) as f, open(out_path, "w") as out:
        for line in f:
            tid = line.strip()
            if not tid:
                continue
            try:
                for record in export_thread(tid, assistant_id):
                    out.write(json.dumps(record) + "\n")
            except Exception as exc:
                print(f"skip {tid}: {exc}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: python export_threads.py thread_ids.txt asst_xxx out.ndjson")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
```

Run it:

```bash
python export_threads.py thread_ids.txt asst_xxxxxxxxxxxxxxxxxxxxxxxx threads.ndjson
```

## Output format

Each line of `threads.ndjson` is one message:

```json
{"thread_id": "thread_abc", "assistant_id": "asst_xxx", "message_id": "msg_001", "role": "user", "text": "Build a CSV parser", "created_at": 1714000000}
{"thread_id": "thread_abc", "assistant_id": "asst_xxx", "message_id": "msg_002", "role": "assistant", "text": "Here's a CSV parser:\n\n```python\nimport csv\n...```", "created_at": 1714000004}
```

This shape is what the [next step](04-import.md) consumes.

## Multi-assistant exports

If you have several assistants, run the script once per assistant with the right `assistant_id`. Don't merge their threads — each assistant typically maps to one Engramia **project** (see step 4).

## Performance notes

- The OpenAI list endpoint is rate-limited (~500 req/min for Tier 1 accounts). With 100 messages per page, that's 50,000 messages/min wallclock.
- For very large exports (>100k threads), parallelize across processes with one OpenAI key per worker, or batch by thread_id chunks.
- Save partial progress — a long export that crashes at thread 9,000 of 10,000 is recoverable if `out.ndjson` is append-mode and you keep a `done_thread_ids.txt` checkpoint.

## Next

[Bulk-import to Engramia](04-import.md) takes this NDJSON file and writes it as Engramia patterns under the right scope.
