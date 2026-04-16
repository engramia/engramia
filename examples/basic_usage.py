# SPDX-License-Identifier: BUSL-1.1
"""Basic Engramia usage — learn, recall, evaluate, metrics.

Setup:
    pip install engramia[openai]
    export OPENAI_API_KEY=sk-...

Run:
    python examples/basic_usage.py
"""

from engramia import Memory
from engramia.providers import JSONStorage, OpenAIEmbeddings, OpenAIProvider

# ---------------------------------------------------------------------------
# 1. Create a Memory instance
# ---------------------------------------------------------------------------
# LLM is required for evaluate() and compose(). Omit it for learn/recall only.
mem = Memory(
    llm=OpenAIProvider(model="gpt-4.1"),
    embeddings=OpenAIEmbeddings(),  # text-embedding-3-small by default
    storage=JSONStorage(path="./engramia_data"),
)

# ---------------------------------------------------------------------------
# 2. Learn — record successful agent runs
# ---------------------------------------------------------------------------
# Simulated outputs from a "CSV parser" agent
csv_code = """
import csv
from statistics import mean, stdev

def analyze_csv(path: str) -> dict:
    with open(path) as f:
        rows = list(csv.DictReader(f))
    values = [float(r["amount"]) for r in rows]
    return {"mean": mean(values), "stdev": stdev(values), "count": len(values)}
"""

result = mem.learn(
    task="Parse CSV file and compute descriptive statistics (mean, stdev, count)",
    code=csv_code,
    eval_score=8.5,
    output="{'mean': 42.3, 'stdev': 12.1, 'count': 150}",
)
print(f"Stored: {result.stored}, patterns: {result.pattern_count}")

# Store a second pattern for a different task
mem.learn(
    task="Fetch JSON data from REST API and validate schema",
    code="import requests\ndata = requests.get(url).json()\nassert 'id' in data",
    eval_score=7.0,
)

# ---------------------------------------------------------------------------
# 3. Recall — semantic search for similar tasks
# ---------------------------------------------------------------------------
matches = mem.recall(
    task="Read CSV and calculate averages",
    limit=3,
)

print(f"\nFound {len(matches)} match(es):")
for m in matches:
    print(f"  [{m.reuse_tier}] similarity={m.similarity:.2f}  task={m.pattern.task[:60]}")
    # m.pattern_key can be used to delete this pattern later
    # mem.delete_pattern(m.pattern_key)

# ---------------------------------------------------------------------------
# 4. Evaluate — multi-LLM scoring of agent output
# ---------------------------------------------------------------------------
eval_result = mem.evaluate(
    task="Parse CSV file and compute descriptive statistics",
    code=csv_code,
    num_evals=3,  # 3 independent LLM evaluations, median aggregation
)
print(f"\nEval score: {eval_result.median_score:.1f}/10")
print(f"High variance: {eval_result.high_variance}")
print(f"Feedback: {eval_result.feedback[:120]}")

# ---------------------------------------------------------------------------
# 5. Feedback — recurring issues for prompt injection
# ---------------------------------------------------------------------------
# After multiple evaluations, Engramia surfaces recurring quality issues.
feedback = mem.get_feedback(task_type="csv", limit=3)
if feedback:
    print("\nRecurring issues to inject into your coder prompt:")
    for issue in feedback:
        print(f"  - {issue}")

# ---------------------------------------------------------------------------
# 6. Metrics
# ---------------------------------------------------------------------------
m = mem.metrics
print(f"\nMetrics: {m.runs} runs | {m.success_rate:.0%} success rate | {m.pattern_count} patterns")

# ---------------------------------------------------------------------------
# 7. Maintenance — pattern aging (run periodically, e.g. weekly)
# ---------------------------------------------------------------------------
pruned = mem.run_aging()
print(f"Aging: {pruned} low-score patterns pruned")
