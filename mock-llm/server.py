# SPDX-License-Identifier: BSL-1.1
"""Mock OpenAI-compatible LLM server for integration testing.

Implements /v1/chat/completions and /v1/embeddings with deterministic
responses. No real LLM calls — returns fixed data suitable for testing
Engramia's learn/recall/evaluate/compose pipeline.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Engramia Mock LLM", version="1.0.0")

EMBEDDING_DIM = 1536

# Fixed eval-style response that Engramia's evaluator expects
EVAL_JSON = """{
  "scores": {"accuracy": 7, "relevance": 8, "completeness": 7},
  "overall_score": 7.3,
  "reasoning": "Mock evaluation — deterministic score for testing.",
  "suggestions": ["This is a mock suggestion for testing purposes."]
}"""


def _deterministic_embedding(text: str) -> list[float]:
    """Generate a deterministic embedding from text via MD5 seeding."""
    digest = hashlib.md5(text.encode()).hexdigest()
    # Expand 32 hex chars into EMBEDDING_DIM floats in [-1, 1]
    values = []
    for i in range(EMBEDDING_DIM):
        # Cycle through digest bytes for determinism
        byte_val = int(digest[(i * 2) % 32:(i * 2) % 32 + 2], 16)
        values.append((byte_val / 255.0) * 2 - 1)
    return values


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "mock-llm"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    model = body.get("model", "gpt-4.1-mini")
    messages = body.get("messages", [])

    # Detect if this is an evaluation request (contains scoring instructions)
    last_content = messages[-1].get("content", "") if messages else ""
    is_eval = any(
        kw in last_content.lower()
        for kw in ("score", "evaluat", "accuracy", "relevance", "overall_score")
    )

    if is_eval:
        content = EVAL_JSON
    else:
        content = (
            "This is a mock LLM response for testing. "
            "The pattern has been processed successfully."
        )

    return JSONResponse(
        {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": sum(len(m.get("content", "")) // 4 for m in messages),
                "completion_tokens": len(content) // 4,
                "total_tokens": sum(len(m.get("content", "")) // 4 for m in messages)
                + len(content) // 4,
            },
        }
    )


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> JSONResponse:
    body = await request.json()
    model = body.get("model", "text-embedding-3-small")
    input_data = body.get("input", "")

    # Handle both string and list inputs
    if isinstance(input_data, str):
        texts = [input_data]
    else:
        texts = input_data

    data = []
    for i, text in enumerate(texts):
        data.append(
            {
                "object": "embedding",
                "index": i,
                "embedding": _deterministic_embedding(str(text)),
            }
        )

    total_tokens = sum(len(str(t)) // 4 for t in texts)

    return JSONResponse(
        {
            "object": "list",
            "data": data,
            "model": model,
            "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
        }
    )


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": "gpt-4.1-mini",
                    "object": "model",
                    "owned_by": "mock",
                },
                {
                    "id": "text-embedding-3-small",
                    "object": "model",
                    "owned_by": "mock",
                },
            ],
        }
    )
