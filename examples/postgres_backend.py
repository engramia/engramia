"""PostgreSQL + pgvector backend — production-ready persistent storage.

Use this setup for:
- Multi-instance / horizontally scaled deployments
- Thousands of patterns (pgvector HNSW index for fast vector search)
- Production SaaS with strong durability guarantees

Setup:
    pip install engramia[openai,postgres]
    export OPENAI_API_KEY=sk-...
    export DATABASE_URL=postgresql://user:password@localhost:5432/engramia

    # Start PostgreSQL with pgvector (Docker):
    docker run -d --name pgvector \
        -e POSTGRES_DB=engramia \
        -e POSTGRES_USER=engramia \
        -e POSTGRES_PASSWORD=secret \
        -p 5432:5432 \
        pgvector/pgvector:pg16

    # Run Alembic migrations:
    alembic upgrade head

Run:
    python examples/postgres_backend.py
"""

import os

from engramia import Memory
from engramia.providers import OpenAIEmbeddings, OpenAIProvider
from engramia.providers.postgres import PostgresStorage

DATABASE_URL = os.environ["DATABASE_URL"]

# ---------------------------------------------------------------------------
# 1. Create Memory instance with PostgreSQL storage
# ---------------------------------------------------------------------------
# PostgresStorage connects to PostgreSQL + pgvector.
# Uses HNSW index for fast approximate nearest-neighbour vector search.
# Embedding dimension must match OpenAIEmbeddings default (1536-dim).
storage = PostgresStorage(database_url=DATABASE_URL)

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),   # 1536-dim, must match the pgvector column
    storage=storage,
)

# ---------------------------------------------------------------------------
# 2. Usage is identical to JSON storage — just a different backend
# ---------------------------------------------------------------------------
result = mem.learn(
    task="Classify customer support tickets by urgency (low/medium/high)",
    code="""
def classify_ticket(text: str, llm) -> str:
    prompt = f"Classify the urgency of this support ticket: {text}\\nUrgency: "
    return llm.call(prompt).strip().lower()
""",
    eval_score=8.2,
    output="high",
)
print(f"Stored: {result.stored} | Total patterns: {result.pattern_count}")

# ---------------------------------------------------------------------------
# 3. Recall uses pgvector HNSW for fast vector similarity search
# ---------------------------------------------------------------------------
matches = mem.recall("Categorize support messages by priority", limit=5)
print(f"\nRecall: {len(matches)} match(es)")
for m in matches:
    print(f"  [{m.reuse_tier}] {m.similarity:.3f} — {m.pattern.task[:70]}")

# ---------------------------------------------------------------------------
# 4. Export patterns for backup or migration
# ---------------------------------------------------------------------------
records = mem.export()
print(f"\nExported {len(records)} patterns (JSONL-compatible)")

# Restore from backup:
# imported = mem.import_data(records, overwrite=False)
# print(f"Imported: {imported} patterns")

# ---------------------------------------------------------------------------
# 5. PostgreSQL-specific: connection pooling is handled internally.
#    For high throughput, use the REST API (which creates one Memory instance)
#    rather than creating many Memory instances in parallel.
# ---------------------------------------------------------------------------
print(f"\nStorage type: {mem.storage_type}")   # "postgres"
print(f"Metrics: {mem.metrics}")
