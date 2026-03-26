# Webhook SDK

A lightweight HTTP client for the Engramia REST API. Uses only `urllib` — no external dependencies.

## Installation

No extra dependencies needed — the webhook SDK is included in the base `engramia` package.

```bash
pip install engramia
```

## Quick start

```python
from engramia.sdk.webhook import EngramiaWebhook

hook = EngramiaWebhook(url="http://localhost:8000", api_key="sk-...")

# Learn
hook.learn(task="Parse CSV", code=code, eval_score=8.5)

# Recall
matches = hook.recall(task="Read CSV and compute averages")
```

## Usage from any language

The webhook SDK is a thin wrapper over the REST API. You can call the same endpoints from any language:

```bash
# Learn
curl -X POST http://localhost:8000/v1/learn \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"task": "Parse CSV", "code": "import csv...", "eval_score": 8.5}'

# Recall
curl -X POST http://localhost:8000/v1/recall \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"task": "Read CSV and compute averages", "limit": 3}'

# Metrics
curl -H "Authorization: Bearer sk-..." http://localhost:8000/v1/metrics
```

See [REST API](../rest-api.md) for the full endpoint reference.
