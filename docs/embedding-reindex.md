# Embedding Model Migration

When you change the embedding model (e.g. from `text-embedding-3-small` to a local model),
existing pattern embeddings become incompatible. Engramia detects this at startup and logs a warning,
but does **not** automatically reindex.

## When to reindex

- After changing `ENGRAMIA_EMBEDDING_MODEL`
- After switching between OpenAI and local embeddings (`ENGRAMIA_LOCAL_EMBEDDINGS`)
- After upgrading a local model version (sentence-transformers)

## How to reindex

### CLI (recommended)

```bash
# Preview what would be re-embedded (no writes)
engramia reindex --path ./engramia_data --dry-run

# Re-embed all patterns
engramia reindex --path ./engramia_data
```

### What happens

1. All stored patterns are iterated
2. Each pattern's task text is re-embedded with the current provider
3. Old embedding vectors are replaced with new ones
4. Pattern data (task, code, score, metadata) is **not modified**

### Important notes

- **Downtime:** Recall quality degrades during reindex (mixed old/new embeddings)
- **Duration:** ~1 second per pattern (OpenAI API), ~0.1s per pattern (local)
- **Cost:** One embedding API call per pattern (for OpenAI)
- **Dimension change:** If the new model produces different-dimension vectors (e.g. 1536 → 384),
  existing embeddings are automatically replaced — no manual cleanup needed
- **PostgreSQL:** The pgvector HNSW index is updated in-place; no manual `REINDEX` needed

## Verifying the reindex

```bash
# Check that recall works after reindex
engramia recall "your test query" --limit 3

# Check embedding metadata
engramia status --path ./engramia_data
```

## Rolling reindex (zero-downtime)

For production deployments with high recall traffic:

1. Deploy new instance with the new embedding model
2. Run `engramia reindex` on the new instance
3. Switch traffic to the new instance
4. Decommission the old instance
