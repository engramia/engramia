# Migrations

Coming from another memory or agent platform? These guides walk you through migrating to Engramia step by step.

Each migration is split into small focused units — read them in order on your first pass, or jump to the one you need from search.

## Available migrations

| From | Status | Sunset / motivation |
|------|--------|---------------------|
| [OpenAI Assistants API](openai-assistants/index.md) | Available | Assistants API sunsets **26 August 2026**. Threads, files, run state stop persisting. |

## What a migration guide covers

Every migration in this section is structured the same way:

1. **Concept mapping** — how the source platform's primitives map onto Engramia's (scopes, patterns, embeddings, jobs, skills).
2. **Cutover code** — minimal before/after diff that shows the new client wiring.
3. **Data export** — extracting your existing state from the source platform.
4. **Bulk import** — bringing that state into Engramia with the correct scope assignment.
5. **Tools / files** — what carries over directly, what needs adapting.
6. **Dual-write strategy** — running both systems in parallel until you have confidence.
7. **Verification & rollback** — pre-cutover checklist, post-cutover smoke tests, rollback plan.

## Migration support

The first 30 customers get hands-on migration support from the Engramia team — code review, scope-mapping advice, and a parallel-run window. Reach out at [sales@engramia.dev](mailto:sales@engramia.dev) before you start.

## Don't see your platform?

Open an issue at [github.com/engramia/engramia/issues](https://github.com/engramia/engramia/issues) describing your source platform — we publish migrations on demand based on customer signal.
