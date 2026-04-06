# Pydantic AI Integration

Engramia provides `EngramiaCapability` for Pydantic AI agents — a drop-in capability that recalls patterns before each run and learns from the result.

## Installation

```bash
pip install "engramia[openai,pydantic-ai]"
```

## Quick start

```python
from pydantic_ai import Agent
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.pydantic_ai import EngramiaCapability

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

agent = Agent('openai:gpt-4o', capabilities=[EngramiaCapability(mem)])
result = agent.run_sync("Build a CSV parser")
```

**What happens behind the scenes:**

1. `before_run` — recalls similar past tasks from Engramia memory
2. `before_model_request` — injects recalled patterns into model messages
3. Agent executes normally
4. `after_run` — stores the task + output as a success pattern

## EngramiaCapability parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auto_learn` | `True` | Store successful outputs as patterns |
| `auto_recall` | `True` | Recall patterns before each run |
| `min_score` | `7.0` | Eval score assigned when learning |
| `recall_limit` | `3` | Max patterns to recall per run |

## System prompt decorator (manual control)

For manual control over recall injection:

```python
from pydantic_ai import Agent, RunContext
from engramia.sdk.pydantic_ai import engramia_system_prompt

agent = Agent('openai:gpt-4o')

@agent.system_prompt
def inject_memory(ctx: RunContext) -> str:
    return engramia_system_prompt(mem, ctx, base="You are a Python expert.")
```

## With dependencies

```python
from dataclasses import dataclass
from pydantic_ai import Agent

@dataclass
class MyDeps:
    task: str
    user_id: str

agent = Agent(
    'openai:gpt-4o',
    deps_type=MyDeps,
    capabilities=[EngramiaCapability(mem)],
)

result = await agent.run("Build a CSV parser", deps=MyDeps(task="Build a CSV parser", user_id="u1"))
```

The capability extracts the task from `deps.task` (or `deps.input`, `deps.query`, etc.) for recall.

## Structured output

```python
from pydantic import BaseModel
from pydantic_ai import Agent

class CodeResult(BaseModel):
    code: str
    explanation: str

agent = Agent('openai:gpt-4o', output_type=CodeResult, capabilities=[EngramiaCapability(mem)])
result = agent.run_sync("Build a CSV parser")
print(result.output.code)
# The full output is learned by Engramia for future recall
```

## Thread safety

`EngramiaCapability` implements `for_run()` which returns a fresh instance for each run, making it safe for concurrent usage.
