# OpenAI Agents SDK Integration

Engramia provides `EngramiaRunHooks` and `engramia_instructions()` for the OpenAI Agents SDK (`openai-agents`).

## Installation

```bash
pip install "engramia[openai,openai-agents]"
```

## Quick start

```python
from agents import Agent, Runner
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# Dynamic instructions — recalled patterns are injected into the system prompt
agent = Agent(
    name="coder",
    instructions=engramia_instructions(mem, base="You are a senior Python developer."),
)

# RunHooks — auto-learn from completed runs
result = await Runner.run(agent, "Build a CSV parser", hooks=EngramiaRunHooks(mem))
```

**What happens behind the scenes:**

1. `engramia_instructions` — recalls similar past tasks and appends them to the system prompt
2. Agent executes normally
3. `on_agent_end` — stores the task + output as a success pattern

## EngramiaRunHooks parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auto_learn` | `True` | Store successful agent outputs as patterns |
| `min_score` | `7.0` | Eval score assigned when learning from runs |
| `recall_limit` | `3` | Max patterns to recall (used by `engramia_instructions`) |

## engramia_instructions parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base` | `""` | Base system prompt to extend with recalled context |
| `recall_limit` | `3` | Max patterns to recall per run |

## Hooks only (without dynamic instructions)

If you prefer static instructions and only want post-run learning:

```python
agent = Agent(name="coder", instructions="You are a developer.")

hooks = EngramiaRunHooks(mem, auto_learn=True, min_score=8.0)
result = await Runner.run(agent, "Build a web scraper", hooks=hooks)
```

## Multi-agent with handoffs

RunHooks fire for every agent in the handoff chain, so each agent's output is learned separately:

```python
from agents import Agent, Runner

triage = Agent(name="triage", instructions="Route tasks to the right agent.", handoffs=[coder, reviewer])
coder = Agent(name="coder", instructions=engramia_instructions(mem, base="Write code."))
reviewer = Agent(name="reviewer", instructions="Review code for quality.")

result = await Runner.run(triage, "Build and review a CSV parser", hooks=EngramiaRunHooks(mem))
```

## Sync usage

```python
result = Runner.run_sync(agent, "Build a CSV parser", hooks=EngramiaRunHooks(mem))
```
