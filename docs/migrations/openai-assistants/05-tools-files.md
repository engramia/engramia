# 5. Tools & files mapping

The Assistants API bundled three "tools" with every assistant: `code_interpreter`, `file_search`, and arbitrary function calling. Migration treats each differently.

!!! note "Prerequisites"
    [Cutover code](02-cutover.md) shows the agent definition. This page extends that with tool wiring.

## Function calling — keeps working unchanged

Your custom function tools port over directly. The OpenAI Agents SDK has the same JSON-schema function-calling primitive, just wired through the `Agent(tools=[...])` arg instead of `client.beta.assistants.create(tools=[...])`.

```python
from agents import Agent, function_tool

@function_tool
def get_weather(city: str) -> str:
    """Return the current weather for a city."""
    return weather_client.fetch(city)

agent = Agent(
    name="weather-bot",
    instructions=engramia_instructions(memory, base="You answer weather questions."),
    tools=[get_weather],
    model="gpt-4.1",
)
```

What changes:

- The `@function_tool` decorator replaces the JSON-schema dict you fed `client.beta.assistants.create(tools=[{"type": "function", ...}])`.
- Engramia hooks (`EngramiaRunHooks`) capture the **full output** of the agent run, including any tool call results. You don't need to instrument tool calls separately.

## `code_interpreter` — kept, but now in your code

OpenAI's hosted code-interpreter sandbox is **not** part of Engramia. It's still part of the OpenAI Agents SDK if you want it, or you can swap it for your own runner.

```python
from agents import Agent, CodeInterpreterTool

agent = Agent(
    name="data-analyst",
    tools=[CodeInterpreterTool()],   # OpenAI's hosted sandbox
    instructions=engramia_instructions(memory, base="You analyze CSV data."),
    model="gpt-4.1",
)
```

If you want to self-host (avoid the OpenAI sandbox dependency or its egress costs), replace `CodeInterpreterTool()` with a custom `@function_tool` that runs Python in a container you control. Engramia is agnostic to which one you pick.

## `file_search` — replaced by Engramia embeddings

This is the biggest concrete change. In the Assistants API:

```python
client.beta.assistants.create(
    tools=[{"type": "file_search"}],
    tool_resources={
        "file_search": {"vector_store_ids": ["vs_xxx"]}
    },
)
```

In Engramia, file search is built into recall. There is no separate "file search" tool — you upload text content as patterns, and `engramia_instructions()` injects the relevant ones automatically.

### Migrating an existing vector store

Three steps:

1. **Download the files**. OpenAI's vector store stores the original files; download via `client.files.content(file_id)`.
2. **Extract text**. PDFs, Word docs, etc., need text extraction (`pypdf`, `python-docx`, or [unstructured.io](https://unstructured.io)). Engramia stores text embeddings, not binaries.
3. **Chunk and learn**. Split each document into ~500-token chunks; store each chunk as a pattern.

```python
from engramia import Memory
from pypdf import PdfReader

memory = Memory()

def chunk_text(text: str, size: int = 2000) -> list[str]:
    """Naive chunker — adapt to your domain."""
    return [text[i:i + size] for i in range(0, len(text), size)]

def import_pdf(path: str, source_name: str):
    reader = PdfReader(path)
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for i, chunk in enumerate(chunk_text(full_text)):
        memory.learn(
            task=f"{source_name} (chunk {i})",
            code=chunk,
            eval_score=5.0,
            source="import",
            run_id=f"file:{source_name}",
        )

import_pdf("./manuals/api-reference.pdf", "api-reference.pdf")
```

The chunker above is intentionally naive. For production, use a sentence-boundary chunker (`langchain.text_splitter.RecursiveCharacterTextSplitter` works fine, even outside LangChain).

### What you lose, what you gain

| Lose | Gain |
|---|---|
| Hosted file extraction (OpenAI did PDF parsing for you) | Full control over chunking strategy |
| Per-assistant vector store binding | Multi-agent shared embeddings within one scope |
| Native multimodal (image search via vision) | (Workaround: pre-extract image captions and store as patterns) |

For most production teams the trade-off is favorable — pre-extraction gives you better chunk quality, and shared embeddings reduce duplicate uploads.

## Skills (advanced, optional)

If you have function tools that you want to make **searchable across your team**, register them as Engramia Skills:

```python
memory.register_skills(pattern_key, ["weather", "geocoding"])
matches = memory.find_by_skills(["weather"])
```

Skills are not a 1:1 mapping for Assistants tools — they're a strict superset. Use them when one team's pattern should be findable by another team's agent. Read more in [Skills API](../../api-reference.md).

## Next

[Dual-write & cutover](06-dual-write.md) — how to run both systems in parallel until you're confident.
