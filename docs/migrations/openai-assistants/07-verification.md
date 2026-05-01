# 7. Verification & rollback

Pre-cutover checklist, post-cutover smoke tests, and the exact rollback path if something breaks.

## Pre-cutover checklist

Tick every box before flipping the read path in [step 6](06-dual-write.md).

### Code

- [ ] `pip show engramia` reports `0.6.6` (or your pinned version) on every host serving traffic.
- [ ] `python -c "from engramia.sdk.openai_agents import EngramiaRunHooks, engramia_instructions; print('ok')"` prints `ok`.
- [ ] Your agent's `instructions=` argument uses `engramia_instructions(memory, base=...)`, not a static string.
- [ ] Every `Runner.run(...)` call passes `hooks=EngramiaRunHooks(memory)`.

### Data

- [ ] Backfill from [step 4](04-import.md) is complete — `GET /v1/metrics` reports `pattern_count` ≥ expected.
- [ ] Spot-check 5 random patterns: `GET /v1/recall?task=<sample-user-prompt>&limit=3` returns relevant results.
- [ ] Pattern store size is **realistic** — if you imported 100k threads and got 100 patterns, the dedup threshold ate everything; investigate before continuing.

### Scope & RBAC

- [ ] `ENGRAMIA_TENANT_ID` and `ENGRAMIA_PROJECT_ID` are set per service. Wrong scope = recall pulls patterns from the wrong customer.
- [ ] At least one Engramia API key has the `editor` role (needed for `learn`/`import`); user-facing services need only `reader`.
- [ ] If you self-host, you have a backup of the `engramia_data/` (JSON) or PostgreSQL DB taken **today**.

### Observability

- [ ] Engramia health: `curl https://api.engramia.dev/v1/health` returns `200 ok`.
- [ ] Your error budget tracks `engramia_*` metrics (pattern_count, avg_eval_score, success_rate). See [Monitoring](../../monitoring.md).
- [ ] Compare-log volume from [step 6](06-dual-write.md) is non-zero for at least 7 consecutive days.

## Post-cutover smoke tests

Run all five within 30 minutes of flipping each rollout step (5%, 25%, 50%, 100%).

### 1. End-to-end agent round-trip

```python
import asyncio
from agents import Runner
# import your actual agent + hooks here

async def smoke():
    result = await Runner.run(agent, "Hello, are you there?", hooks=hooks)
    assert result.final_output, "empty response"
    print(result.final_output)

asyncio.run(smoke())
```

Pass condition: response is non-empty and on-topic.

### 2. Recall returns relevant patterns

```bash
curl "https://api.engramia.dev/v1/recall?task=<a%20task%20you%20definitely%20backfilled>&limit=3" \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

Pass condition: response contains 1-3 matches with `reuse_tier` of `duplicate` or `adapt`.

### 3. Learn writes back

After running step 1's smoke, immediately `GET /v1/metrics` again and verify `pattern_count` increased by 1. If it did not, `EngramiaRunHooks` is not wired correctly — recheck `Runner.run(..., hooks=hooks)`.

### 4. Audit log records the cutover

```bash
curl "https://api.engramia.dev/v1/audit?limit=5" \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

Pass condition: recent events show `learn` actions with `source=api`. If everything is `source=import`, no live traffic is reaching Engramia.

### 5. No quota exhaustion

```bash
curl https://api.engramia.dev/v1/billing/status \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

Pass condition: `pattern_count_used` is well below `pattern_count_limit`. If you're at 95%, the bulk import overshot — either upgrade the plan or run scoped deletion of the lowest-eval-score patterns. See [Pricing](../../pricing.md).

## Rollback

If any smoke test fails or quality drops in the first 24 hours after a rollout step:

### Stage 1 — Flip the flag back

```python
def engramia_enabled(user_id):
    return False   # was: variant ramp logic
```

That's the entire rollback for the read path. Threads still exist on the OpenAI side until 26 August 2026, so reads continue to work.

### Stage 2 — Stop the shadow writes (only if Engramia itself is the problem)

```python
# Comment out the shadow learn call:
# asyncio.create_task(_shadow_learn(...))
```

Engramia data accumulated during dual-write is preserved — you can resume the cutover later without re-importing.

### Stage 3 — Re-import only if pattern store is corrupt

If the issue is that imported patterns are wrong (bad scope, bad chunking, polluted with PII), purge and re-import:

```bash
# Scope-bounded delete, dry run first:
curl -X POST "https://api.engramia.dev/v1/governance/delete-scope?dry_run=true" \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"

# Then real:
curl -X POST "https://api.engramia.dev/v1/governance/delete-scope" \
  -H "Authorization: Bearer $ENGRAMIA_API_KEY"
```

Then re-run [step 4](04-import.md) with the fix.

## You're done

Once the 100% rollout has been live for 7 days and step 6 stage 4 is complete (no new Threads being created), the migration is **complete**. Some teams keep the dual-write running past 26 August 2026 just to capture audit-log evidence; that's optional and costs you a small amount of OpenAI quota.

Now ship.

---

If something in this guide didn't match what you saw, please open an issue at [github.com/engramia/engramia/issues](https://github.com/engramia/engramia/issues) — migration docs decay fastest, and we want to know.
