# Providers

Engramia uses abstract base classes for LLM, embeddings, and storage. You can mix and match providers freely.

## LLM Providers

LLM providers are used by `evaluate()`, `compose()`, and `evolve_prompt()`. If you only need `learn()` and `recall()`, you can skip the LLM provider entirely.

### OpenAI

```python
from engramia.providers import OpenAIProvider

llm = OpenAIProvider(model="gpt-4.1")  # default
llm = OpenAIProvider(model="gpt-4.1-mini")
llm = OpenAIProvider(model="gpt-4.1-nano")
```

Requires `OPENAI_API_KEY` environment variable or pass `api_key=` to constructor.

Includes automatic retry (3 attempts) on transient errors.

### Anthropic

```python
from engramia.providers import AnthropicProvider

llm = AnthropicProvider(model="claude-sonnet-4-20250514")
```

Requires `ANTHROPIC_API_KEY` environment variable.

Lazy imports — the `anthropic` package is only loaded when first used.

### Custom LLM provider

Implement the `LLMProvider` ABC:

```python
from engramia.providers.base import LLMProvider

class MyProvider(LLMProvider):
    def generate(self, prompt: str) -> str:
        # Call your LLM and return the response text
        return my_llm_call(prompt)
```

## Embedding Providers

### OpenAI Embeddings

```python
from engramia.providers import OpenAIEmbeddings

embeddings = OpenAIEmbeddings()  # default: text-embedding-3-small
embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
```

Uses native batch embedding for efficiency.

### Local Embeddings (no API key)

```python
from engramia.providers import LocalEmbeddings

embeddings = LocalEmbeddings()  # default: all-MiniLM-L6-v2 (384-dim)
```

Uses `sentence-transformers` — runs entirely locally, no API key needed.

Install with:

```bash
pip install "engramia[local]"
```

### Custom embedding provider

Implement the `EmbeddingProvider` ABC:

```python
from engramia.providers.base import EmbeddingProvider

class MyEmbeddings(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        # Return a list of embedding vectors
        return [my_embed(t) for t in texts]
```

## Storage Backends

### JSON Storage

```python
from engramia.providers import JSONStorage

storage = JSONStorage(path="./brain_data")
```

- Thread-safe with `threading.Lock`
- Atomic writes (write to temp file, then rename)
- In-memory index for fast lookups
- Brute-force cosine similarity for vector search
- Best for: development, single-machine deployments

### PostgreSQL + pgvector

```python
from engramia.providers import PostgresStorage

storage = PostgresStorage(database_url="postgresql://user:pass@localhost:5432/brain")
```

- Uses pgvector extension for vector similarity search
- HNSW index for fast approximate nearest neighbor search
- SQLAlchemy 2.x with connection pooling
- Alembic migrations for schema management
- Best for: production, multi-instance deployments

Install with:

```bash
pip install "engramia[postgres]"
```

See [Deployment](deployment.md) for PostgreSQL setup details.

### Custom storage backend

Implement the `StorageBackend` ABC:

```python
from engramia.providers.base import StorageBackend

class MyStorage(StorageBackend):
    def save(self, key: str, data: dict, embedding: list[float] | None = None) -> None: ...
    def load(self, key: str) -> dict | None: ...
    def delete(self, key: str) -> bool: ...
    def list_keys(self, prefix: str = "") -> list[str]: ...
    def search_similar(
        self, embedding: list[float], limit: int, prefix: str = ""
    ) -> list[tuple[str, float]]: ...
```

## Combining providers

```python
from engramia import Memory
from engramia.providers import (
    OpenAIProvider, AnthropicProvider,
    OpenAIEmbeddings, LocalEmbeddings,
    JSONStorage, PostgresStorage,
)

# OpenAI + local embeddings + JSON (no embedding API costs)
mem = Memory(
    llm=OpenAIProvider(),
    embeddings=LocalEmbeddings(),
    storage=JSONStorage(path="./data"),
)

# Anthropic + OpenAI embeddings + PostgreSQL
mem = Memory(
    llm=AnthropicProvider(model="claude-sonnet-4-20250514"),
    embeddings=OpenAIEmbeddings(),
    storage=PostgresStorage(database_url="postgresql://..."),
)

# Embeddings only (no LLM) — learn/recall work, evaluate/compose raise ProviderError
mem = Memory(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./data"),
)
```
