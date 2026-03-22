# Agent Brain

Self-learning memory layer for AI agent frameworks.

> Work in progress — see [roadmap.md](roadmap.md) for implementation status.

## Quick start

```python
from agent_brain import Brain
from agent_brain.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage

brain = Brain(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./brain_data"),
)

# Learn from a run
brain.learn(task="Parse CSV and compute stats", code=code, eval_score=8.5)

# Recall relevant agents for a new task
matches = brain.recall(task="Read CSV and calculate averages", limit=5)
```
