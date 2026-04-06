# AutoGen Integration

Engramia provides `EngramiaMemory` — an implementation of AutoGen's `Memory` interface that plugs directly into `AssistantAgent`.

## Installation

```bash
pip install "engramia[openai,autogen]"
```

## Quick start

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.autogen import EngramiaMemory, learn_from_result

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

model_client = OpenAIChatCompletionClient(model="gpt-4o")
agent = AssistantAgent(
    name="coder",
    model_client=model_client,
    system_message="You are a senior Python developer.",
    memory=[EngramiaMemory(mem)],
)

result = await agent.run(task="Build a CSV parser")

# Learn from the result (AutoGen Memory has no post-run hook)
learn_from_result(mem, task="Build a CSV parser", result=result)
```

**What happens behind the scenes:**

1. Before each LLM call, `update_context()` recalls relevant patterns and injects a `SystemMessage`
2. Agent executes normally with the enriched context
3. After the run, call `learn_from_result()` to store the output

## EngramiaMemory parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `recall_limit` | `3` | Max patterns to recall per LLM call |
| `name` | `"engramia"` | Display name for this memory source |

## learn_from_result parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `task` | — | Task description (required) |
| `result` | — | AutoGen `TaskResult` from `agent.run()` |
| `eval_score` | `7.0` | Eval score to assign to the learned pattern |

## With teams

```python
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination

coder = AssistantAgent(
    name="coder",
    model_client=model_client,
    memory=[EngramiaMemory(mem)],
)
reviewer = AssistantAgent(
    name="reviewer",
    model_client=model_client,
    system_message="Review code for quality and suggest improvements.",
    memory=[EngramiaMemory(mem)],
)

team = RoundRobinGroupChat(
    [coder, reviewer],
    termination_condition=MaxMessageTermination(6),
)

result = await team.run(task="Build and review a CSV parser")
learn_from_result(mem, task="Build and review a CSV parser", result=result)
```

## Direct query and add

```python
ag_mem = EngramiaMemory(mem)

# Query patterns directly
result = await ag_mem.query("CSV parsing")
for item in result.results:
    print(item.content)

# Add patterns manually
from autogen_core.memory import MemoryContent
await ag_mem.add(MemoryContent(content="Use pandas for CSV: pd.read_csv('file.csv')"))
```

## Multiple memory sources

AutoGen supports multiple memory instances — combine Engramia with other sources:

```python
from autogen_core.memory import ListMemory

local_notes = ListMemory(name="notes")
await local_notes.add(MemoryContent(content="Always validate input before processing."))

agent = AssistantAgent(
    name="coder",
    model_client=model_client,
    memory=[EngramiaMemory(mem), local_notes],
)
```
