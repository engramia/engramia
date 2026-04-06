"""Pydantic AI — Engramia as a drop-in Capability.

Setup:
    pip install "engramia[openai,pydantic-ai]"
    export OPENAI_API_KEY=sk-...

Run:
    python examples/pydantic_ai_capability.py
"""

from engramia import Memory
from engramia.providers import OpenAIEmbeddings, OpenAIProvider, JSONStorage
from engramia.sdk.pydantic_ai import EngramiaCapability

# 1. Setup Memory
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# 2. Create Pydantic AI agent with Engramia capability
from pydantic_ai import Agent

agent = Agent(
    'openai:gpt-4o',
    system_prompt="You are a senior Python developer.",
    capabilities=[EngramiaCapability(mem, recall_limit=3)],
)

# 3. Run tasks — each run recalls past patterns and learns from the result
tasks = [
    "Write a function to merge two sorted lists",
    "Write a function to binary search a sorted list",
    "Write a function to merge and search a sorted list",  # should recall both
]

for task in tasks:
    print(f"\n--- Task: {task} ---")
    result = agent.run_sync(task)
    print(f"Output: {str(result.output)[:200]}...")
    print(f"Patterns stored: {mem.metrics.pattern_count}")
