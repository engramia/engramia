# 1. Concept mapping

Before writing any migration code, get a clear picture of how Assistants API primitives map onto Engramia's. Most map cleanly. Where they don't, you usually get something stronger (eval-weighted ranking, RBAC, audit log).

## The mapping table

| OpenAI Assistants | Engramia | Why it differs |
|---|---|---|
| **Thread** (per-user message history) | **Scope** (`tenant_id`, `project_id`) | Engramia scopes are multi-user-aware. One Thread maps to one project; many users can share that project under RBAC. |
| **Message** (linear, append-only) | **Pattern** (`task`, `code`, `eval_score`) | Patterns are eval-weighted and decayable. Recall ranks them by outcome quality, not chronological position. |
| **File** (vector store per assistant) | **Embedding** (pgvector + HNSW) | Files in Engramia are scope-aware — one upload, many readers. No per-assistant rebind. |
| **Run** (transient request state) | **Async job** (DB-backed queue) | Runs in Engramia survive restarts. Use `Prefer: respond-async` to opt in. |
| **Tool** (assistant-bound, JSON schema) | **Skill** (cross-tenant searchable) | Skills are first-class entities you can search, evaluate, and reuse across tenants — not bound to one assistant. |
| **Assistant** (instructions + tools + model) | **Agent** (Agents SDK) + Engramia memory | The agent definition stays in your code. Engramia replaces the persistence layer underneath it. |

## Three concrete consequences

### a) Scopes are not Threads

OpenAI's Thread is a **single-user, single-conversation** container. Engramia's scope is a **multi-user, multi-session** boundary that enforces RBAC and audit logging.

- One Engramia project ≈ one product feature, one team, or one customer (depending on your isolation model).
- Within a scope, there is no "conversation" object — patterns are recalled by semantic similarity to the current task, not by who said what when.
- If you genuinely need per-user isolation, run one tenant or project per user. The hosted plans size for this.

### b) Recall replaces "load the thread"

In Assistants:

```python
thread = client.beta.threads.retrieve(thread_id)
# all messages get re-sent on the next run
```

In Engramia:

```python
matches = memory.recall(task="Build a CSV parser", limit=3)
# only the top-3 most relevant patterns are injected
```

The default recall window is 3 patterns, ranked by `(similarity × success_score × recency_decay)`. You can override `limit` and add `min_score` filters. See [Recall API](../../api-reference.md).

### c) Files are not files

OpenAI files are blobs you upload and bind to one assistant's vector store. Engramia uses **embeddings** — vectors stored in pgvector with an HNSW index.

- You upload text content (or extracted text from PDFs/images), not raw binary.
- One embedding can be recalled by any agent in the same scope.
- Storage cost is per-vector, not per-file. A 50-page PDF chunked into 100 vectors costs the same as 100 short notes.

If your assistant relied on multimodal (image/audio) files, you'll need to either pre-extract text or use the multimodal-capable provider directly (the OpenAI Agents SDK supports this) — Engramia stores text embeddings only.

## Next

Now that the primitives line up in your head, see [Cutover code](02-cutover.md) for the actual diff.
