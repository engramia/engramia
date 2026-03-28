# CrewAI Integration

Engramia provides `EngramiaCrewCallback` — a drop-in integration for [CrewAI](https://crewai.com) that gives your agent crews persistent reusable execution memory.

After each task, Engramia automatically stores what worked. Before the next run, it recalls similar patterns and prepends them to task descriptions as context — so your crews improve with every execution.

## Installation

```bash
pip install "engramia[openai,crewai]"
```

## Quick start

```python
from crewai import Agent, Crew, Task
from engramia import Memory
from engramia.providers import JSONStorage, OpenAIEmbeddings, OpenAIProvider
from engramia.sdk.crewai import EngramiaCrewCallback

# 1. Create Memory instance
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# 2. Create callback
callback = EngramiaCrewCallback(mem, auto_learn=True, auto_recall=True)

# 3. Build your crew as normal
researcher = Agent(role="Researcher", goal="Find accurate information", backstory="...")
task = Task(description="Summarize recent advances in transformer architecture", agent=researcher)
crew = Crew(agents=[researcher], tasks=[task], task_callback=callback.task_callback)

# 4. Run — Engramia injects recalled context, then learns from the result
result = callback.kickoff(crew)
print(result)
```

`callback.kickoff(crew)` is a convenience wrapper that:

1. Calls `inject_recall(crew.tasks)` — prepends recalled patterns to each task description
2. Calls `crew.kickoff()` and returns the result

## Three usage modes

### Mode 1 — Auto-learn only (simplest)

Learns from completed tasks. No pre-task context injection.

```python
callback = EngramiaCrewCallback(mem, auto_learn=True, auto_recall=False)
crew = Crew(
    agents=[agent],
    tasks=[task],
    task_callback=callback.task_callback,
)
crew.kickoff()
```

### Mode 2 — Manual inject + auto-learn

More control: inject recall before kickoff, learn after.

```python
callback = EngramiaCrewCallback(mem, auto_learn=True, auto_recall=True)

# Inject recalled patterns into task descriptions *before* kickoff
callback.inject_recall(crew.tasks)

crew = Crew(agents=[agent], tasks=[task], task_callback=callback.task_callback)
crew.kickoff()
```

### Mode 3 — kickoff wrapper (recommended)

The cleanest option — handles recall + kickoff in one call.

```python
callback = EngramiaCrewCallback(mem, auto_learn=True, auto_recall=True)
result = callback.kickoff(crew, inputs={"topic": "AI memory systems"})
```

## Callback parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auto_learn` | `True` | Call `mem.learn()` after each task via `task_callback` |
| `auto_recall` | `True` | Inject recalled patterns into task descriptions before kickoff |
| `default_score` | `7.0` | Eval score used when storing auto-learned patterns |
| `recall_limit` | `3` | Number of patterns to recall per task |

## What gets injected

When `inject_recall` runs, it appends a block like this to each task description:

```
---
**Relevant prior patterns from Engramia memory:**
1. [DUPLICATE] Summarize GitHub README into key points
   ```
   bullets = llm.call(f"Summarize:\n{readme}")[:3]
   ```
2. [ADAPT] Extract key takeaways from research papers
   ```
   summary = llm.call(f"Extract 3 takeaways from:\n{text}")
   ```
```

The agent sees this as part of the task description and uses it as reference context.

## Manual recall + context building

For more control over how context is presented to your agents:

```python
# Recall patterns relevant to a task
matches = mem.recall("Summarize research papers", limit=3)

# Format as context for the agent backstory or task description
context = "\n".join(
    f"- [{m.reuse_tier}] {m.pattern.task}: {m.pattern.design.get('code', '')[:200]}"
    for m in matches
)

researcher = Agent(
    role="Researcher",
    goal="Summarize research papers concisely",
    backstory=f"You are an expert summarizer. Relevant past solutions:\n{context}",
)
```

## Full example: self-improving research crew

```python
from crewai import Agent, Crew, Task
from engramia import Memory
from engramia.providers import JSONStorage, OpenAIEmbeddings, OpenAIProvider
from engramia.sdk.crewai import EngramiaCrewCallback

mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)
callback = EngramiaCrewCallback(mem, auto_learn=True, auto_recall=True, default_score=7.5)

topics = [
    "Recent advances in vector databases",
    "State-of-the-art agent memory architectures",
    "Comparison of RAG vs fine-tuning for domain adaptation",
]

for topic in topics:
    researcher = Agent(
        role="AI Research Analyst",
        goal="Produce a concise, accurate technical summary",
        backstory="You specialize in AI systems research.",
    )
    task = Task(
        description=f"Research and summarize: {topic}",
        agent=researcher,
        expected_output="3–5 paragraph technical summary with key findings",
    )
    crew = Crew(agents=[researcher], tasks=[task], task_callback=callback.task_callback)

    result = callback.kickoff(crew)
    print(f"\n--- {topic} ---")
    print(str(result)[:300])

# After several runs, Engramia surfaces recurring quality issues
feedback = mem.get_feedback(limit=3)
if feedback:
    print("\nRecurring issues (use in agent backstory):")
    for issue in feedback:
        print(f"  - {issue}")

# Run aging to prune outdated patterns
pruned = mem.run_aging()
print(f"\nPatterns: {mem.metrics.pattern_count} | Pruned: {pruned}")
```

## Skill tagging

Tag patterns with explicit capabilities for precise retrieval:

```python
# After learning, tag the stored pattern
matches = mem.recall("summarize research papers", limit=1)
if matches:
    mem.register_skills(matches[0].pattern_key, ["summarization", "research", "markdown"])

# Later: find patterns by capability
results = mem.find_by_skills(["summarization", "research"])
print(f"Found {len(results)} pattern(s) with both skills")
```

## Using the REST API instead of the Python SDK

If your crew runs in a separate process or a different language, use the webhook SDK:

```python
from engramia.sdk.webhook import EngramiaWebhook

client = EngramiaWebhook(url="http://localhost:8000", api_key="your-key")

# Learn from a completed task
client.learn(task="Summarize research paper", code=result_text, eval_score=8.0)

# Recall before next task
matches = client.recall(task="Summarize academic paper", limit=3)
```

See the [REST API reference](../rest-api.md) and [Webhook SDK](webhook.md) for full details.
