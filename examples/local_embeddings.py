"""Fully offline usage — local embeddings, no API key required.

Uses sentence-transformers for embeddings (runs on CPU, no cloud calls).
Combine with Anthropic or any local LLM provider for a fully self-hosted setup.

Setup:
    pip install engramia[local]
    # Optional: add Anthropic LLM for evaluate/compose
    pip install engramia[local,anthropic]
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python examples/local_embeddings.py
"""

import os

from engramia import Memory
from engramia.providers import JSONStorage
from engramia.providers.local_embeddings import LocalEmbeddings

# ---------------------------------------------------------------------------
# 1. Local embeddings — sentence-transformers, no API key
# ---------------------------------------------------------------------------
# Default model: all-MiniLM-L6-v2 (384-dim, ~80 MB, CPU-friendly)
# Larger/more accurate option: "all-mpnet-base-v2" (768-dim)
embeddings = LocalEmbeddings(model_name="all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# 2. Optional: Anthropic LLM (for evaluate/compose/evolve)
# ---------------------------------------------------------------------------
llm = None
if os.getenv("ANTHROPIC_API_KEY"):
    from engramia.providers.anthropic import AnthropicProvider
    llm = AnthropicProvider(model="claude-sonnet-4-6")
    print("Using Anthropic LLM for evaluate/compose")
else:
    print("No LLM configured — learn/recall work without it, evaluate/compose require one")

# ---------------------------------------------------------------------------
# 3. Create Brain (fully local, no cloud calls for learn/recall)
# ---------------------------------------------------------------------------
brain = Memory(
    llm=llm,
    embeddings=embeddings,   # 384-dim local vectors
    storage=JSONStorage(path="./brain_data_local"),
)

# ---------------------------------------------------------------------------
# 4. Learn — runs fully offline
# ---------------------------------------------------------------------------
patterns = [
    (
        "Parse unstructured log files and extract ERROR lines",
        "import re\nerrors = [l for l in open('app.log') if re.search(r'ERROR', l)]",
        8.0,
    ),
    (
        "Convert Markdown to HTML using mistune",
        "import mistune\nhtml = mistune.html(markdown_text)",
        7.5,
    ),
    (
        "Retry a function with exponential backoff",
        "import time\nfor i in range(retries):\n    try: return fn()\n    except: time.sleep(2**i)",
        9.0,
    ),
]

for task, code, score in patterns:
    result = brain.learn(task=task, code=code, eval_score=score)
    print(f"Stored: {result.stored} — {task[:50]}")

# ---------------------------------------------------------------------------
# 5. Recall — semantic search using local vectors
# ---------------------------------------------------------------------------
print("\n--- Recall demo ---")

queries = [
    "Extract error messages from log files",
    "Convert markdown documents to HTML format",
    "Add retry logic with backoff to API calls",
]

for query in queries:
    matches = brain.recall(task=query, limit=2)
    print(f"\nQuery: {query[:50]}")
    for m in matches:
        print(f"  [{m.reuse_tier}] {m.similarity:.3f} — {m.pattern.task[:60]}")

# ---------------------------------------------------------------------------
# 6. Skill registry — tag patterns with capabilities
# ---------------------------------------------------------------------------
all_matches = brain.recall(task="log file parsing", limit=1)
if all_matches:
    key = all_matches[0].pattern_key
    brain.register_skills(key, ["log_parsing", "regex", "file_io"])

skill_results = brain.find_by_skills(["log_parsing"])
print(f"\nSkill search 'log_parsing': {len(skill_results)} pattern(s)")

# ---------------------------------------------------------------------------
# 7. Evaluate (requires LLM)
# ---------------------------------------------------------------------------
if llm:
    eval_result = brain.evaluate(
        task="Parse log files and extract error lines",
        code="errors = [l for l in open('app.log') if 'ERROR' in l]",
        num_evals=2,
    )
    print(f"\nEval score: {eval_result.median_score:.1f}/10")
    print(f"Feedback: {eval_result.feedback[:120]}")
else:
    print("\nSkipping evaluate — no LLM configured")

# ---------------------------------------------------------------------------
# 8. Metrics
# ---------------------------------------------------------------------------
m = brain.metrics
print(f"\nMetrics: {m.pattern_count} patterns | {m.runs} runs | storage: {brain.storage_type}")
