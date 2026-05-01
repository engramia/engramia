# Migrating from OpenAI Assistants API

The OpenAI Assistants API **sunsets on 26 August 2026**. From that date, the entire `/v1/assistants` surface returns `410 Gone` — Threads, Messages, Runs, and assistant-scoped Files stop persisting.

This guide is the canonical migration path from Assistants API to **Engramia + the OpenAI Agents SDK**. The model layer (`gpt-4.1`, function calling, streaming) does not change. What changes is where memory, files, and run state live.

!!! info "Audience"
    Production teams with an active Assistants integration — typically a `client.beta.assistants.create()` + `client.beta.threads.runs.*` loop, with one Thread per user/conversation.

## Reading order

Read these in order on your first pass. Each unit is ~5 minutes; the whole guide is ~30 minutes.

| # | Guide | What you'll do |
|---|-------|----------------|
| 1 | [Concept mapping](01-concepts.md) | Understand how Threads, Messages, Files, Runs, and Tools map onto Engramia primitives. |
| 2 | [Cutover code](02-cutover.md) | Replace `client.beta.assistants.*` with `Agent` + `EngramiaRunHooks`. |
| 3 | [Export Threads from OpenAI](03-export-threads.md) | Enumerate threads and dump messages to NDJSON. |
| 4 | [Bulk-import to Engramia](04-import.md) | Convert dumped messages into Engramia patterns with the right scope. |
| 5 | [Tools & files mapping](05-tools-files.md) | What happens to `code_interpreter`, `file_search`, and function calling. |
| 6 | [Dual-write & cutover](06-dual-write.md) | Run both systems in parallel; flip the read path when confident. |
| 7 | [Verification & rollback](07-verification.md) | Pre-cutover checklist, post-cutover smoke tests, rollback plan. |

## Working example repository

A runnable end-to-end example lives at **[github.com/engramia/examples/tree/main/openai-assistants-migration](https://github.com/engramia/examples/tree/main/openai-assistants-migration)** — `before/` (Assistants API), `after/` (Engramia + Agents SDK), and `backfill/` (export + import scripts). Pin to the same Engramia version as you have in production.

## Prerequisites

- An Engramia instance — either [hosted](https://app.engramia.dev/register) or self-hosted (`pip install engramia[openai-agents]`)
- An API key with `editor` role or higher (needed for `/v1/learn` and `/v1/import`)
- The OpenAI API key you used for Assistants — needed for the data export step
- Python 3.12+ (the `openai-agents` package requirement)

## What this guide does **not** cover

- Migrating to a different LLM vendor (Anthropic, Gemini). Engramia supports those, but the cutover diff in step 2 keeps OpenAI as the model layer to minimize moving parts. See [Providers](../../providers.md) for vendor swaps.
- Migrating from `/chat/completions` directly — those callers don't have Threads or assistants to migrate. They simply add `EngramiaRunHooks` or `engramia_instructions()`. See [OpenAI Agents integration](../../integrations/openai-agents.md).
- The Responses API. OpenAI's official Assistants successor. If you've already moved to Responses, you can still benefit from Engramia's eval-weighted recall — the wiring is the same as step 2 of this guide. See [OpenAI Agents integration](../../integrations/openai-agents.md) for the Responses-API variant.

## Migration window

```
April 2026                    August 26, 2026
   |                                  |
   v                                  v
[ start migration ] ---------> [ Assistants API 410 Gone ]
                  ^                   ^
                  |                   |
            ~4-month window           hard cutover
```

Engramia recommends starting at least **8 weeks** before the sunset to leave room for the dual-write window in step 6.
