# Integration Examples

## OpenAI Agents SDK

```python
from agents import Agent, Runner
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions

mem = Memory(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# Dynamic instructions with recalled patterns + auto-learn hooks
agent = Agent(
    name="coder",
    instructions=engramia_instructions(mem, base="You are a Python developer."),
)
result = await Runner.run(agent, "Build a CSV parser", hooks=EngramiaRunHooks(mem))
```

## Anthropic Agent SDK

```python
from engramia.sdk.anthropic_agents import engramia_query

# One call: recall → run → learn
async for message in engramia_query(mem, prompt="Build a CSV parser"):
    print(message)
```

## Pydantic AI

```python
from pydantic_ai import Agent
from engramia.sdk.pydantic_ai import EngramiaCapability

agent = Agent('openai:gpt-4o', capabilities=[EngramiaCapability(mem)])
result = agent.run_sync("Build a CSV parser")
```

## AutoGen

```python
from autogen_agentchat.agents import AssistantAgent
from engramia.sdk.autogen import EngramiaMemory, learn_from_result

agent = AssistantAgent(name="coder", model_client=client, memory=[EngramiaMemory(mem)])
result = await agent.run(task="Build a CSV parser")
learn_from_result(mem, task="Build a CSV parser", result=result)
```

## LangChain

```python
from langchain.chains import LLMChain
from langchain.llms import OpenAI
from engramia import Memory
from engramia.sdk.langchain import EngramiaCallback

# Setup
memory = Memory(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

callback = EngramiaCallback(
    memory,
    auto_learn=True,    # store successful runs
    auto_recall=True,   # recall patterns before execution
    min_score=5.0,      # only store runs scoring >= 5.0
    recall_limit=3,     # recall top 3 patterns
)

# Use as a chain callback
chain = LLMChain(llm=OpenAI(), prompt=prompt, callbacks=[callback])
result = chain.run("Parse CSV and compute statistics")

# Access recalled context for a specific run
recalled = callback.get_recalled_context(run_id)
```

## CrewAI

```python
from crewai import Agent, Crew, Task
from engramia import Memory
from engramia.sdk.crewai import EngramiaCrewCallback

memory = Memory(
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

callback = EngramiaCrewCallback(
    memory,
    auto_learn=True,    # learn from task outputs
    auto_recall=True,   # inject recalled patterns into task descriptions
    default_score=7.0,  # default eval score for learned patterns
)

agent = Agent(role="Data Analyst", goal="Analyze data", backstory="...")
task = Task(description="Parse CSV and compute statistics", agent=agent)
crew = Crew(agents=[agent], tasks=[task])

# Option 1: Full convenience wrapper (inject + kickoff)
result = callback.kickoff(crew, inputs={"topic": "data analysis"})

# Option 2: Manual control
callback.inject_recall(crew.tasks)
crew = Crew(agents=[agent], tasks=[task], task_callback=callback.task_callback)
crew.kickoff()

# Check how many patterns were stored
print(f"Learned {callback.get_learned_count()} patterns")
```

## MCP Server (Claude Desktop / Claude Code)

Add to your MCP client config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "engramia": {
      "command": "engramia-mcp",
      "env": {
        "ENGRAMIA_DATA_PATH": "/path/to/engramia_data",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

Available MCP tools:

| Tool | Description |
|------|-------------|
| `engramia_learn` | Store a successful agent run |
| `engramia_recall` | Find relevant patterns for a task |
| `engramia_evaluate` | Score agent code quality (multi-evaluator) |
| `engramia_compose` | Decompose task into pipeline stages |
| `engramia_feedback` | Get recurring quality issues |
| `engramia_metrics` | View aggregate statistics |
| `engramia_aging` | Run pattern decay and pruning |

## Webhook Client

```python
from engramia.sdk.webhook import WebhookClient

# Fire-and-forget event posting to external systems
client = WebhookClient(
    url="https://your-app.com/hooks/engramia",
    secret="your-webhook-secret",
)

# Posts are non-blocking with exponential backoff on failure
client.post_learn(pattern_key="patterns/abc123", eval_score=8.5)
client.post_recall(task="Parse CSV", matches=3)
```

## REST API (direct)

```python
import httpx

client = httpx.Client(
    base_url="https://api.engramia.dev",
    headers={"Authorization": "Bearer engramia_sk_..."},
)

# Learn
client.post("/v1/learn", json={
    "task": "Parse CSV and compute statistics",
    "code": "import csv\n...",
    "eval_score": 8.5,
})

# Recall
resp = client.post("/v1/recall", json={"task": "Parse CSV file", "limit": 5})
matches = resp.json()["matches"]
```
