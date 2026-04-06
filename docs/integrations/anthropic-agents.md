# Anthropic Agent SDK Integration

Engramia provides `engramia_query()`, `recall_system_prompt()`, and `engramia_hooks()` for the Anthropic Agent SDK (`claude-agent-sdk`).

## Installation

```bash
pip install "engramia[openai,anthropic-agents]"
```

## Quick start

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.anthropic_agents import engramia_query

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# One-liner: recall → run → learn
async for message in engramia_query(mem, prompt="Build a CSV parser"):
    print(message)
```

**What happens behind the scenes:**

1. Recalled patterns are injected into the system prompt
2. Agent executes normally, yielding messages
3. On `ResultMessage`, the output is stored as a success pattern

## engramia_query parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `base_system_prompt` | `""` | Base system prompt to extend with recalled context |
| `recall_limit` | `3` | Max patterns to recall |
| `auto_learn` | `True` | Store the final result as a pattern |
| `min_score` | `7.0` | Eval score assigned when learning |
| `options` | `None` | Optional `ClaudeAgentOptions` to extend |

## Manual system prompt injection

For full control over the agent options:

```python
from claude_agent_sdk import ClaudeAgentOptions, query
from engramia.sdk.anthropic_agents import recall_system_prompt

prompt = recall_system_prompt(
    mem,
    task="Build a CSV parser",
    base="You are a senior developer.",
    recall_limit=5,
)

async for message in query(
    prompt="Build a CSV parser",
    options=ClaudeAgentOptions(
        system_prompt=prompt,
        allowed_tools=["Read", "Edit", "Bash"],
    ),
):
    print(message)
```

## PostToolUse hooks

For observability on tool usage:

```python
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from engramia.sdk.anthropic_agents import engramia_hooks, recall_system_prompt

hooks = engramia_hooks(mem, auto_learn=True)
prompt = recall_system_prompt(mem, task="Build a CSV parser", base="You are a developer.")

options = ClaudeAgentOptions(
    system_prompt=prompt,
    hooks=hooks,
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Build a CSV parser")
    async for message in client.receive_response():
        print(message)
```

## With custom ClaudeAgentOptions

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    allowed_tools=["Read", "Write", "Bash"],
    max_turns=10,
)

async for message in engramia_query(
    mem,
    prompt="Build a web scraper",
    options=options,
    recall_limit=5,
    min_score=8.0,
):
    print(message)
```
