"""Engramia REST API client — using the lightweight webhook SDK.

No extra dependencies beyond the standard library. Connects to a running
Engramia API server (local or hosted).

Setup:
    # Start the server locally:
    docker compose up
    # or:
    pip install engramia[api,openai]
    export OPENAI_API_KEY=sk-...
    engramia serve

    # (Optional) Set an API key for auth:
    export ENGRAMIA_API_KEYS=my-secret-key

Run:
    python examples/rest_api_client.py
"""

import os

from engramia.sdk.webhook import EngramiaWebhook

# ---------------------------------------------------------------------------
# 1. Connect to the API server
# ---------------------------------------------------------------------------
client = EngramiaWebhook(
    url=os.getenv("ENGRAMIA_URL", "http://localhost:8000"),
    api_key=os.getenv("ENGRAMIA_API_KEY"),  # None = dev mode (no auth)
    timeout=30,
)

# Health check
health = client.health()
print(f"Server: {health.get('status')} | storage: {health.get('storage_type')}")

# ---------------------------------------------------------------------------
# 2. Learn — record a successful agent run
# ---------------------------------------------------------------------------
client.learn(
    task="Summarize a GitHub repository README into 3 bullet points",
    code="response = llm.call(f'Summarize this README:\\n{readme_text}')\nbullets = response.strip().split('\\n')[:3]",
    eval_score=8.0,
    output="• Fast: ...\n• Self-learning: ...\n• Framework-agnostic: ...",
)
print("Learned pattern stored.")

# ---------------------------------------------------------------------------
# 3. Recall — find similar patterns
# ---------------------------------------------------------------------------
matches = client.recall(
    task="Summarize documentation into key points",
    limit=5,
)
print(f"\nFound {len(matches)} match(es):")
for m in matches:
    print(f"  [{m['reuse_tier']}] similarity={m['similarity']:.2f}  task={m['pattern']['task'][:60]}")

# ---------------------------------------------------------------------------
# 4. Evaluate — multi-LLM scoring (requires LLM configured on server)
# ---------------------------------------------------------------------------
eval_result = client.evaluate(
    task="Summarize a GitHub README into bullet points",
    code="bullets = llm.call(prompt)[:3]",
    num_evals=2,
)
print(f"\nEval score: {eval_result.get('median_score', 'N/A')}/10")

# ---------------------------------------------------------------------------
# 5. Compose — multi-agent pipeline design
# ---------------------------------------------------------------------------
pipeline = client.compose(task="Fetch GitHub repo, summarize README, post to Slack")
if pipeline.get("valid"):
    print("\nPipeline stages:")
    for stage in pipeline.get("stages", []):
        print(f"  {stage['name']}: {stage['task'][:60]}")
else:
    print(f"\nPipeline invalid: {pipeline.get('contract_errors')}")

# ---------------------------------------------------------------------------
# 6. Feedback — surface recurring quality issues
# ---------------------------------------------------------------------------
feedback = client.feedback(task_type="summarization", limit=3)
if feedback:
    print("\nRecurring issues:")
    for issue in feedback:
        print(f"  - {issue}")

# ---------------------------------------------------------------------------
# 7. Metrics
# ---------------------------------------------------------------------------
metrics = client.metrics()
print(
    f"\nMetrics: {metrics.get('runs')} runs | "
    f"{metrics.get('success_rate', 0):.0%} success | "
    f"{metrics.get('pattern_count')} patterns"
)

# ---------------------------------------------------------------------------
# 8. Delete a pattern (if you got a pattern_key from recall)
# ---------------------------------------------------------------------------
if matches:
    key = matches[0].get("pattern_key")
    if key:
        deleted = client.delete_pattern(key)
        print(f"\nDeleted pattern: {deleted}")

# ---------------------------------------------------------------------------
# 9. Skill-based search
# ---------------------------------------------------------------------------
client.register_skills(
    pattern_key=matches[1]["pattern_key"] if len(matches) > 1 else "",
    skills=["summarization", "markdown"],
)
skill_matches = client.find_by_skills(required=["summarization"])
print(f"\nSkill search: {len(skill_matches)} pattern(s) with 'summarization' skill")
