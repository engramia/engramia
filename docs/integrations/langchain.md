# LangChain Integration

Engramia provides an `EngramiaCallback` that hooks into any LangChain chain for automatic learning and recall.

## Installation

```bash
pip install "engramia[openai,langchain]"
```

## Quick start

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.langchain import EngramiaCallback

# Initialize Memory
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# Create callback
callback = EngramiaCallback(mem, auto_learn=True, auto_recall=True)
```

## Attach to any chain

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOpenAI(model="gpt-4.1")
prompt = ChatPromptTemplate.from_template("Write Python code to: {input}")
chain = prompt | llm | StrOutputParser()

# Run with Memory callback — learning happens automatically
result = chain.invoke(
    {"input": "Parse a CSV file and compute column averages"},
    config={"callbacks": [callback]},
)
```

**What happens behind the scenes:**

1. `on_chain_start` — Memory recalls similar past tasks and logs context
2. Chain executes normally
3. `on_chain_end` — Memory stores the task + output as a success pattern

## Callback parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `auto_learn` | `True` | Store successful chain outputs as patterns |
| `auto_recall` | `True` | Search for similar patterns before chain starts |
| `min_score` | `5.0` | Minimum eval score to store a pattern |
| `recall_limit` | `3` | Max patterns to recall per chain run |

## Use recalled context in prompts

```python
# Manual recall + prompt enrichment
matches = mem.recall(task="Parse JSON API response", limit=3)

context = "\n".join(
    f"- Previous solution for '{m.pattern.task}': {m.pattern.design.get('code', '')[:200]}"
    for m in matches
)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a Python expert. Use these relevant past solutions as reference:\n{context}"),
    ("human", "{input}"),
])

chain = prompt | llm | StrOutputParser()
result = chain.invoke({"input": "Parse JSON API response", "context": context})
```

## Full example: self-improving code agent

```python
from engramia import Memory
from engramia.providers import OpenAIProvider, OpenAIEmbeddings, JSONStorage
from engramia.sdk.langchain import EngramiaCallback
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Setup
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)
callback = EngramiaCallback(mem, auto_learn=True, auto_recall=True)
llm = ChatOpenAI(model="gpt-4.1")

# Agent loop
tasks = [
    "Write a function to merge two sorted arrays",
    "Implement binary search on a sorted list",
    "Write a function to find duplicates in an array",
]

for task in tasks:
    matches = mem.recall(task, limit=3)
    context = ""
    if matches:
        context = "Relevant past solutions:\n" + "\n".join(
            f"- {m.pattern.task}: {m.pattern.design.get('code', '')[:300]}"
            for m in matches
        )

    prompt = ChatPromptTemplate.from_messages([
        ("system", f"You write Python functions.\n{context}"),
        ("human", "{input}"),
    ])
    chain = prompt | llm | StrOutputParser()

    result = chain.invoke({"input": task}, config={"callbacks": [callback]})

    # Evaluate and learn with actual score
    eval_result = mem.evaluate(task=task, code=result)
    mem.learn(task=task, code=result, eval_score=eval_result.median_score)

# Maintain memory
mem.run_aging()
print(f"Patterns: {mem.metrics.pattern_count}, "
      f"Success rate: {mem.metrics.success_rate:.0%}")
```
