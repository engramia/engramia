"""LangChain integration — auto-learn from chain runs and recall relevant context.

Engramia attaches to LangChain via a callback handler. It automatically:
- Recalls relevant patterns before each chain run (adds context to memory)
- Learns from successful chain outputs after each run

Setup:
    pip install engramia[openai,langchain]
    export OPENAI_API_KEY=sk-...

Run:
    python examples/langchain_callback.py
"""

from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from engramia import Memory
from engramia.providers import JSONStorage, OpenAIEmbeddings, OpenAIProvider
from engramia.sdk.langchain import EngramiaCallback

# ---------------------------------------------------------------------------
# 1. Create Memory instance
# ---------------------------------------------------------------------------
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),
    storage=JSONStorage(path="./engramia_data"),
)

# ---------------------------------------------------------------------------
# 2. Create EngramiaCallback
# ---------------------------------------------------------------------------
callback = EngramiaCallback(
    mem,
    auto_learn=True,    # Store successful chain outputs as patterns
    auto_recall=True,   # Recall relevant patterns before each chain run
    min_score=5.0,      # Only learn if run "succeeded" (score threshold)
    recall_limit=3,     # How many patterns to recall
)

# ---------------------------------------------------------------------------
# 3. Build a LangChain chain with the callback
# ---------------------------------------------------------------------------
llm = ChatOpenAI(model="gpt-4.1", temperature=0)

prompt = PromptTemplate(
    input_variables=["input"],
    template="You are a Python expert. Write clean, production-ready code for: {input}",
)

chain = LLMChain(llm=llm, prompt=prompt, callbacks=[callback])

# ---------------------------------------------------------------------------
# 4. Run the chain — Engramia auto-learns and recalls in the background
# ---------------------------------------------------------------------------
tasks = [
    "Parse a CSV file and return descriptive statistics",
    "Fetch JSON from a REST API with retry logic",
    "Parse a CSV file and compute mean and standard deviation",  # Similar to #1 — Engramia will recall
]

for task in tasks:
    print(f"\nTask: {task}")
    result = chain.invoke({"input": task})
    print(f"Output: {result['text'][:120]}...")

# ---------------------------------------------------------------------------
# 5. Check what Engramia learned
# ---------------------------------------------------------------------------
print(f"\nEngramia metrics: {mem.metrics.pattern_count} patterns stored")

# Manually recall for inspection
matches = mem.recall("Calculate statistics from CSV data", limit=3)
print(f"Recall 'statistics from CSV': {len(matches)} match(es)")
for m in matches:
    print(f"  [{m.reuse_tier}] {m.similarity:.2f} — {m.pattern.task[:60]}")

# ---------------------------------------------------------------------------
# 6. Optional: Evolve prompts based on recurring failures (Experimental)
# ---------------------------------------------------------------------------
# After many runs, Engramia surfaces recurring quality issues and can suggest
# improved prompts. Run this after accumulating enough feedback.
#
# result = mem.evolve_prompt(
#     role="coder",
#     current_prompt="You are a Python expert. Write clean, production-ready code for: {task}",
# )
# print(f"\nEvolved prompt:\n{result.improved_prompt}")
# print(f"Rationale: {result.rationale[:200]}")
