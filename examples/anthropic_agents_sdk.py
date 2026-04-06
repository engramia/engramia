"""Anthropic Agent SDK — recall + run + learn in one call.

Setup:
    pip install "engramia[openai,anthropic-agents]"
    export OPENAI_API_KEY=sk-...

Run:
    python examples/anthropic_agents_sdk.py
"""

import asyncio

from engramia import Memory
from engramia.providers import OpenAIEmbeddings, OpenAIProvider, JSONStorage
from engramia.sdk.anthropic_agents import engramia_query

# 1. Setup Memory
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)


# 2. Run with automatic recall and learn
async def main():
    tasks = [
        "Write a function to parse JSON API responses",
        "Write a function to validate JSON schema",
        "Write a function to parse and validate API responses",  # should recall both
    ]

    for task in tasks:
        print(f"\n--- Task: {task} ---")
        async for message in engramia_query(
            mem,
            prompt=task,
            base_system_prompt="You are a senior Python developer.",
            min_score=7.5,
        ):
            # Print message type (SystemMessage, AssistantMessage, ResultMessage)
            print(f"  {type(message).__name__}")

        print(f"Patterns stored: {mem.metrics.pattern_count}")


asyncio.run(main())
