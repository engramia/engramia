# 2. Cutover code

The minimal diff to replace `client.beta.assistants` with the OpenAI Agents SDK + Engramia. This is the path the [working example](https://github.com/engramia/examples/tree/main/openai-assistants-migration) demonstrates end-to-end.

!!! note "Prerequisites"
    Read [Concept mapping](01-concepts.md) first. You need to know what a scope is and why we don't restore "the whole thread" on each call.

## Install

```bash
pip install "engramia[openai-agents,openai]==0.6.6"
```

The `openai-agents` extra pulls in OpenAI's `agents` SDK. The `openai` extra brings the LLM and embedding clients.

## Environment

```bash
# OpenAI — same key you used for Assistants
export OPENAI_API_KEY=sk-...

# Engramia — pick one of:
# Hosted:
export ENGRAMIA_API_KEY=eng_...
export ENGRAMIA_API_URL=https://api.engramia.dev

# Self-hosted with Postgres:
export ENGRAMIA_STORAGE=postgres
export ENGRAMIA_DATABASE_URL=postgresql://engramia:...@localhost:5432/engramia

# Self-hosted with JSON (dev only):
export ENGRAMIA_STORAGE=json
export ENGRAMIA_DATA_PATH=./engramia_data
```

## Before — Assistants API

```python
from openai import OpenAI

client = OpenAI()

assistant = client.beta.assistants.create(
    name="coder",
    model="gpt-4.1",
    instructions="You are a senior developer.",
)

thread = client.beta.threads.create()
client.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="Build a CSV parser.",
)
run = client.beta.threads.runs.create_and_poll(
    thread_id=thread.id,
    assistant_id=assistant.id,
)
messages = client.beta.threads.messages.list(thread_id=thread.id)
print(messages.data[0].content[0].text.value)
```

What this does: creates a new assistant + thread, posts a user message, polls until the run finishes, prints the assistant's reply. Persistence is OpenAI-side (`thread.id` is the persistence key).

## After — Engramia + OpenAI Agents SDK

```python
import asyncio
from agents import Agent, Runner
from engramia import Memory
from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions

memory = Memory()  # picks up ENGRAMIA_* env vars

agent = Agent(
    name="coder",
    instructions=engramia_instructions(
        memory,
        base="You are a senior developer.",
    ),
    model="gpt-4.1",
)

hooks = EngramiaRunHooks(memory)

async def main():
    result = await Runner.run(
        agent,
        "Build a CSV parser.",
        hooks=hooks,
    )
    print(result.final_output)

asyncio.run(main())
```

What this does:

1. `Memory()` picks up the env vars and connects to your storage backend.
2. `engramia_instructions(memory, base=...)` returns a dynamic system-prompt builder. On each run it calls `memory.recall(task=...)` and appends the top-3 patterns to the base instructions.
3. `EngramiaRunHooks(memory)` listens for `on_agent_end` and writes the completed run back via `memory.learn()`. The next time anyone in this scope asks for "Build a CSV parser", the new pattern is in the recall pool.
4. The model, the agent definition, and the user-facing call site are unchanged.

## What you do not need to port

| Assistants API call | Engramia equivalent | Why |
|---|---|---|
| `client.beta.threads.create()` | _(nothing)_ | No Thread object — the `task` string is the implicit conversation key. |
| `client.beta.threads.messages.create()` | `await Runner.run(agent, message)` | The Agents SDK passes input directly. |
| `client.beta.threads.runs.create_and_poll()` | `await Runner.run(...)` | Polling is built-in. |
| `client.beta.assistants.update()` | Edit `Agent(...)` definition + redeploy | Agent config lives in code, not in the OpenAI dashboard. |

## Verify the cutover compiles

```bash
python -c "from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions; print('ok')"
```

Should print `ok`. If you get `ImportError: OpenAI Agents integration requires openai-agents`, install the extra: `pip install "engramia[openai-agents]"`.

## Next

Code is wired but Engramia is empty. To carry your existing Assistants conversation history forward, see [Export Threads from OpenAI](03-export-threads.md). To skip backfill and start fresh, jump to [Dual-write & cutover](06-dual-write.md).
