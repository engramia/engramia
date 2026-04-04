# pgvector HNSW Index Maintenance

Engramia uses pgvector's HNSW (Hierarchical Navigable Small World) index for
approximate nearest-neighbor search on pattern embeddings.

## Index parameters

Set during migration `001_initial`:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `m` | 16 | Max connections per node (higher = better recall, more memory) |
| `ef_construction` | 64 | Build-time search width (higher = better index quality, slower build) |

These are good defaults for up to ~100k patterns. For larger stores, consider
increasing `m` to 32 and `ef_construction` to 128.

## When to rebuild

The HNSW index quality can degrade after heavy churn (many deletes + inserts).
Rebuild when:

- Recall quality drops noticeably (patterns you know exist aren't returned)
- After bulk deletion (e.g. retention policy pruned >50% of patterns)
- After a full reindex (`engramia reindex`)
- After migrating from JSON to PostgreSQL (`engramia migrate`)

## How to rebuild

```sql
-- Check current index size
SELECT pg_size_pretty(pg_relation_size('ix_memory_embeddings_hnsw'));

-- Rebuild the HNSW index (blocks writes during rebuild)
REINDEX INDEX CONCURRENTLY ix_memory_embeddings_hnsw;

-- If CONCURRENTLY fails, use the blocking version:
-- REINDEX INDEX ix_memory_embeddings_hnsw;
```

Via Docker:

```bash
docker compose exec postgres psql -U engramia -d engramia \
  -c "REINDEX INDEX CONCURRENTLY ix_memory_embeddings_hnsw;"
```

## Monitoring index health

```sql
-- Index size vs table size
SELECT
  pg_size_pretty(pg_relation_size('memory_embeddings')) AS table_size,
  pg_size_pretty(pg_relation_size('ix_memory_embeddings_hnsw')) AS index_size;

-- Row count
SELECT count(*) FROM memory_embeddings;
```

## Performance tuning

For search queries, pgvector uses `ef_search` (runtime parameter, default 40):

```sql
-- Increase for better recall at the cost of latency
SET hnsw.ef_search = 100;

-- Check current value
SHOW hnsw.ef_search;
```

Set globally in `postgresql.conf` or per-session for tuning.

## Vacuum

PostgreSQL's `autovacuum` handles routine maintenance. After large bulk
operations, run a manual vacuum:

```sql
VACUUM ANALYZE memory_embeddings;
```
