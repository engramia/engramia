"""OpenAI Agents SDK — auto-recall into system prompt, auto-learn from results.

Setup:
    pip install "engramia[openai,openai-agents]"
    export OPENAI_API_KEY=sk-...

Run:
    python examples/openai_agents_sdk.py
"""

import asyncio

from agents import Agent, Runner

from engramia import Memory
from engramia.providers import OpenAIEmbeddings, OpenAIProvider, JSONStorage
from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions

# 1. Setup Memory
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# 2. Create agent with Engramia-powered dynamic instructions
agent = Agent(
    name="coder",
    instructions=engramia_instructions(
        mem,
        base="You are a senior Python developer. Write clean, tested code.",
    ),
)

# 3. Run with auto-learn hooks
async def main():
    tasks = [
        "Write a function to parse CSV files into dicts",
        "Write a function to compute column averages from a list of dicts",
        "Write a function to read CSV and compute averages",  # should recall both above
    ]

    for task in tasks:
        print(f"\n--- Task: {task} ---")
        result = await Runner.run(agent, task, hooks=EngramiaRunHooks(mem))
        print(f"Output: {str(result.final_output)[:200]}...")
        print(f"Patterns stored: {mem.metrics.pattern_count}")


asyncio.run(main())
