# 6. Dual-write & cutover

You have wired Engramia (step 2), backfilled Threads (steps 3-4), and figured out tools/files (step 5). Now you flip production traffic — but **gradually**, not all at once.

The recommended path: dual-write → compare → flip read path → stop creating new Threads.

!!! warning "Don't rip out Assistants on day one"
    Even if your test suite passes, agent behavior depends on subtle things — recall ordering, scope leakage, prompt drift after instruction changes. Run dual-write for at least one full deploy cycle before flipping the read path.

## Stage 1 — Dual-write

Both systems run on every request. Write to both, but only **read from Assistants** (the trusted system).

```python
async def handle_request(user_id: str, message: str):
    # Read path — still Assistants
    thread_id = lookup_thread(user_id)
    asst_reply = await assistants_run(thread_id, message)

    # Write path — also write to Engramia for shadow capture
    asyncio.create_task(_shadow_learn(user_id, message, asst_reply))

    return asst_reply

async def _shadow_learn(user_id: str, message: str, reply: str):
    """Fire-and-forget — never block the user response on Engramia."""
    try:
        memory.learn(
            task=message[:2000],
            code=reply[:8000],
            eval_score=5.0,
            source="api",
            run_id=f"shadow:{user_id}",
        )
    except Exception as exc:
        log.warning("shadow learn failed: %s", exc)
```

What this gives you:

- Engramia accumulates real production patterns alongside the backfilled history.
- If Engramia is down, only logging breaks — user requests still succeed.
- After a week, you have side-by-side data to compare retrieval quality.

## Stage 2 — Shadow read & compare

Add a second read path that **doesn't go to the user** — purely for diffing.

```python
async def handle_request(user_id: str, message: str):
    thread_id = lookup_thread(user_id)
    asst_reply = await assistants_run(thread_id, message)

    asyncio.create_task(_shadow_compare(user_id, message, asst_reply))
    return asst_reply

async def _shadow_compare(user_id: str, message: str, asst_reply: str):
    try:
        result = await Runner.run(agent, message, hooks=hooks)
        log_compare(
            user_id=user_id,
            task=message,
            assistants_output=asst_reply,
            engramia_output=result.final_output,
        )
    except Exception as exc:
        log.warning("shadow compare failed: %s", exc)
```

Inspect the `log_compare` output for:

- **Length divergence** — Engramia outputs 2× longer than Assistants ⇒ recall is over-injecting; reduce `recall_limit` in `engramia_instructions()`.
- **Wrong-answer rate** — Engramia gives the wrong answer ≥ X% more often ⇒ pattern store is polluted; investigate which patterns are being recalled and re-evaluate them (see step 7's verification checks).
- **Tool-call mismatch** — Engramia calls a different tool than Assistants ⇒ system prompt drift; align the `base=` argument of `engramia_instructions()` with your old assistant `instructions`.

Run this stage for at least 7 days, ideally 14, before stage 3.

## Stage 3 — Flip the read path

A simple feature flag, per-tenant:

```python
async def handle_request(user_id: str, message: str):
    if engramia_enabled(user_id):
        result = await Runner.run(agent, message, hooks=hooks)
        return result.final_output

    # Fallback path — Assistants
    thread_id = lookup_thread(user_id)
    return await assistants_run(thread_id, message)
```

Ramp `engramia_enabled()` from 0% → 5% → 25% → 50% → 100% over 1-2 weeks, watching the compare logs at each step. Roll back instantly if quality drops.

!!! tip "Per-tenant rollouts"
    If your Engramia scope is `(tenant, project)`, ramp tenant-by-tenant instead of percent-of-traffic. This isolates rollback to one tenant if problems surface.

## Stage 4 — Stop creating new Threads

Once 100% read traffic is on Engramia and you've held there for a week:

1. Remove the `client.beta.threads.create()` call.
2. Delete the thread-id lookup table once the deletion is in your audit log (compliance evidence).
3. Stop the dual-write task — Engramia is now the only writer.
4. Optionally, run `engramia evaluate-imported` to upgrade the neutral `eval_score=5.0` patterns from step 4 with real LLM scoring.

## Audit-log evidence

Each cutover stage emits an audit event:

```bash
curl https://api.engramia.dev/v1/audit?action=cutover \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

If you need to demonstrate the migration to compliance/legal (for example because Assistants stored some PII you need to attest deletion of), this is the canonical record.

## Next

[Verification & rollback](07-verification.md) — the checklist you run before declaring victory.
