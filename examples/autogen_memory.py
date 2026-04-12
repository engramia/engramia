"""AutoGen — Engramia as an AssistantAgent Memory source.

Setup:
    pip install "engramia[openai,autogen]" autogen-ext[openai]
    export OPENAI_API_KEY=sk-...

Run:
    python examples/autogen_memory.py
"""

import asyncio

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from engramia import Memory
from engramia.providers import JSONStorage, OpenAIEmbeddings, OpenAIProvider
from engramia.sdk.autogen import EngramiaMemory, learn_from_result

# 1. Setup Memory
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# 2. Create AutoGen agent with Engramia memory
model_client = OpenAIChatCompletionClient(model="gpt-4o")

agent = AssistantAgent(
    name="coder",
    model_client=model_client,
    system_message="You are a senior Python developer. Write clean, tested code.",
    memory=[EngramiaMemory(mem, recall_limit=3)],
)


# 3. Run tasks
async def main():
    tasks = [
        "Write a function to download a file from a URL",
        "Write a function to retry a download on failure",
        "Write a function to download with retry and progress bar",  # should recall both
    ]

    for task in tasks:
        print(f"\n--- Task: {task} ---")
        result = await agent.run(task=task)

        # AutoGen Memory has no post-run hook, so learn explicitly
        learn_from_result(mem, task=task, result=result, eval_score=7.5)

        last_msg = result.messages[-1] if result.messages else None
        print(f"Output: {str(getattr(last_msg, 'content', ''))[:200]}...")
        print(f"Patterns stored: {mem.metrics.pattern_count}")

        # Reset agent for next task (optional — depends on use case)
        await agent.on_reset()


asyncio.run(main())
