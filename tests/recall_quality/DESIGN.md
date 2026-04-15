# Recall Quality Test Suite — Design & Reference

> Revision 3 (2026-04-15) — merged operational reference into design doc.
> Covers both `tests/recall_quality/` (embedding-quality longitudinal suite) and
> `tests/test_features/` (functional regression suite). See **Running the suite**
> below for day-to-day usage; see **Critical findings** for the why behind test rules.

## Purpose

Repeatable benchmark suite that measures Engramia recall quality, learning
dynamics, and subsystem correctness.  Results feed back into system
improvements: if a change regresses recall precision or breaks aging
invariants, we catch it here.

The suite does **not** use agent_factory_v2.  Test agents are deterministic
Python functions — no LLM calls in the hot path (except where explicitly
testing `/evaluate`, `/compose`, `/evolve`).

---

## Critical findings from code review

These corrections invalidate parts of the original v1 design.  Every test
must account for them.

### 1. `recall()` has write side-effects

Every `recall()` call invokes `mark_reused()` on each returned pattern,
adding **+0.1 to success_score** (capped at 10.0).  This means:

- Repeated recall of the same task mutates scores in storage.
- Tests measuring "pure" similarity must either use a fresh dataset per
  assertion or account for score drift.
- Tests that call recall 5 times on the same cluster will have boosted
  the first-returned patterns by up to +0.5.

**Design rule:** when testing raw similarity, call recall **once** per
assertion group.  For tests specifically measuring reuse boost, call
recall N times and assert score delta.

### 2. Deduplication hides results (Jaccard > 0.7)

`_deduplicate_matches()` in `brain.py` groups patterns by word-level
Jaccard similarity > 0.7 and keeps only the highest-scored pattern per
group.  This means:

- If we learn 5 paraphrases of "Load CSV and filter rows", recall might
  return only 1-2 of them (the rest are dedup'd).
- Cross-cluster tests are fine (different domains have low Jaccard).
- Within-cluster tests need **semantically similar but lexically diverse**
  task descriptions to avoid being collapsed.

**Design rule:** task variants within a cluster must have Jaccard < 0.7
to each other.  Pre-validate with `engramia._util.jaccard()`.

### 3. Pattern keys are unique per learn (timestamp-based)

`_pattern_key()` = `patterns/{sha256(task)[:8]}_{time_ms}`.  The same
task learned twice gets two **different** keys.  Tests cannot predict
keys in advance; they must capture keys from `recall()` results or
`learn()` return values (LearnResult doesn't expose the key, but recall
does via `match.pattern_key`).

### 4. Aging depends on real elapsed time

`run_aging()` computes `elapsed_weeks = (now - pattern.timestamp) / 604800`
and applies `score * 0.98^elapsed_weeks`.  Freshly-learned patterns
(seconds old) decay by ~0.000003% — effectively nothing.

**Design rule:** aging tests must either:
- (a) mock `time.time()` to simulate weeks passing, or
- (b) directly manipulate `pattern.timestamp` in storage before calling
  aging, or
- (c) test against the production API with a `--time-warp` helper that
  patches timestamps via direct DB update.

### 5. Eval multiplier lookup is keyed on pattern_key + Jaccard

`get_eval_multiplier(agent_name, task)` scans evals in reverse for an
entry where `agent_name == pattern_key` AND `jaccard(task, eval_task) >= 0.15`.
The multiplier is `0.5 + 0.5 * (score / 10.0)`, so:

| eval_score | multiplier | effective_sim for raw_sim=0.8 |
|------------|------------|-------------------------------|
| 10.0       | 1.00       | 0.80                          |
| 7.5        | 0.875      | 0.70                          |
| 5.0        | 0.75       | 0.60                          |
| 0.0        | 0.50       | 0.40                          |
| (no eval)  | 0.75       | 0.60                          |

This means a pattern with eval_score=5 and raw_sim=0.8 ranks **lower**
than a pattern with eval_score=10 and raw_sim=0.7 (effective 0.60 vs 0.70).

### 6. Import does NOT restore embeddings

`import_data()` calls `storage.save(key, data)` but never calls
`storage.save_embedding(key, embedding)`.  An import/export roundtrip
preserves pattern data but recall will **not find** imported patterns
(no embedding to search against).

**This is a known limitation / potential bug.**  The test should document it.

### 7. Feedback requires count >= 2 to surface

`get_top()` filters `p["count"] >= 2`.  A single `record()` call creates
a pattern with count=1.  To see feedback in `get_feedback()`, the same
(or Jaccard > 0.4 similar) feedback must be recorded **at least twice**.

### 8. Similarity thresholds are embedding-model-dependent

The thresholds (0.92 duplicate, 0.70 adapt, below = fresh) are designed
for OpenAI `text-embedding-3-small`.  Local `sentence-transformers`
produces different similarity distributions.  Production uses OpenAI.

**Design rule:** tests define thresholds relative to a **calibration
step** that measures baseline same-cluster and cross-cluster similarity
for the active embedding model.

---

## Execution modes

| Mode     | Storage     | Embeddings           | LLM              | Use case              |
|----------|-------------|----------------------|-------------------|-----------------------|
| local    | JSONStorage | sentence-transformers| None              | Fast CI, no API keys  |
| remote   | PostgreSQL  | OpenAI (via API)     | OpenAI (via API)  | Production benchmark  |

Selection: `ENGRAMIA_TEST_MODE=local|remote` env var.  Default: `local`.

Remote mode reads `ENGRAMIA_API_URL` + `ENGRAMIA_API_KEY` from env.

---

## Test dimensions (12)

### D1. Recall precision (intra-cluster)

Learn N patterns from the same domain.  Recall with a held-out query
from the same domain.  Assert top-1 similarity exceeds calibrated
threshold.

**Key subtlety:** disable deduplication (`deduplicate=False`) to see
all stored patterns, not just the dedup'd winner.

### D2. Cross-cluster isolation

Learn patterns from 2+ different clusters.  Recall from cluster A.
Assert that results from cluster B (if any) have similarity below
the "adapt" threshold (0.70 for OpenAI, calibrated for local).

### D3. Noise rejection

Recall with a noise task against a populated store.  Assert max
similarity is below the "fresh" threshold.

### D4. Deduplication behavior

Learn 3 tasks with Jaccard > 0.7 to each other but different scores.
Recall with `deduplicate=True`.  Assert only the highest-scored
variant is returned.  Then recall with `deduplicate=False` and assert
all 3 are present.

### D5. Reuse boost accumulation

Learn a pattern.  Recall it 10 times.  Load the pattern directly from
storage and assert `success_score == original + 10 * 0.1` (capped at 10).
Assert `reuse_count == 10`.

### D6. Eval weighting impact

Learn 2 patterns for the same task — one with eval_score=9.0, one with
eval_score=3.0.  Recall with `eval_weighted=True` — high-score pattern
should rank first.  Recall with `eval_weighted=False` — order may differ
(depends on raw similarity alone).

### D7. Learning dynamics (warm-up curve)

Sequential learn/recall cycle:

1. Learn pattern A from cluster.  Recall → context_len_1.
2. Learn pattern B (same cluster).  Recall → context_len_2.
3. ... repeat to N=5.

Assert context_len is non-decreasing.  Note: NOT strictly monotonic
because deduplication may suppress a new pattern if it's too similar
to an existing higher-scored one.

### D8. Pattern aging

**Local mode only** (requires direct storage access):

1. Learn a pattern with eval_score=2.0.
2. Patch its `timestamp` to 52 weeks ago.
3. Run aging.
4. Assert pattern is pruned (score 2.0 * 0.98^52 = 0.70 < 0.1? No,
   2.0 * 0.98^52 ≈ 0.70 — still above 0.1.  Need score < ~0.36 for
   pruning at 52 weeks: 0.36 * 0.98^52 ≈ 0.10).
5. Learn a pattern with eval_score=0.5, patch to 52 weeks ago.
   0.5 * 0.98^52 ≈ 0.175 — still survives.  Need 104 weeks:
   0.5 * 0.98^104 ≈ 0.061 < 0.1.  Or use score=0.2: 0.2 * 0.98^52 ≈ 0.07.
6. Verify that freshly-learned patterns are NOT pruned.
7. Verify reuse-boosted patterns survive longer.

### D9. Feedback lifecycle

1. Record feedback "Missing error handling for edge cases" **3 times**
   (slightly paraphrased — Jaccard > 0.4).
2. Assert `get_feedback()` returns it (count >= 2 ✓).
3. Run `feedback_decay()`.
4. Assert score decreased.
5. Record completely different feedback 1 time.
6. Assert `get_feedback()` does NOT return it (count < 2).

### D10. Skills subsystem

1. Learn 3 patterns.  Register skills: A=["csv", "pandas"],
   B=["csv", "regex"], C=["http", "retry"].
2. Search `["csv"]` `match_all=True` → A and B.
3. Search `["csv", "pandas"]` `match_all=True` → A only.
4. Search `["csv", "http"]` `match_all=False` → A, B, C.
5. Search `["unknown"]` → empty.

### D11. Metrics consistency

1. Note initial metrics (runs_0, pattern_count_0).
2. Run 5 learns, 3 recalls.
3. Assert metrics.runs == runs_0 + 5 (learns record runs; recalls don't).
4. Assert metrics.pattern_count == pattern_count_0 + 5.
5. Assert metrics.success_rate > 0.

### D12. System robustness

- **Empty task** → ValidationError.
- **Huge code** (600 KB) → ValidationError (max 500 KB).
- **eval_score out of range** (11.0, -1.0) → ValidationError.
- **Delete nonexistent pattern** → returns `deleted=False`.
- **Delete same pattern twice** → second returns `deleted=False`.
- **Recall on empty store** → returns empty list, no crash.
- **Unicode task** → learn + recall round-trip succeeds.

---

## Task clusters (12 clusters, 5 variants each)

### Design constraints for task variants

Each variant within a cluster must:
1. Be semantically similar (same domain, similar intent).
2. Have **Jaccard < 0.7** to every other variant (avoids dedup collision).
3. Use different vocabulary / sentence structure.

Jaccard pre-validation formula: `jaccard(a, b) = |words(a) ∩ words(b)| / |words(a) ∪ words(b)|`

---

### C01 — CSV Row Filtering

```
A: "Load CSV file and filter rows where column 'status' equals 'active'"
B: "Read a spreadsheet in CSV format, select only active entries"
C: "Import comma-separated data, keep records matching status=active"
D: "Open tabular CSV dataset, extract rows by status field value"
E: "CSV row selection: retain entries where the status attribute is active"
```

### C02 — CSV Aggregation

```
A: "Group CSV by 'category' column and sum the 'amount' field"
B: "Aggregate tabular data: compute total amounts per category"
C: "Summarize CSV — calculate category-wise sum of amount values"
D: "Pivot CSV by category label, produce sum of numeric amount column"
E: "Per-group totals from comma-separated dataset grouped on category"
```

### C03 — TOML/Config Validation

```
A: "Parse TOML config file and validate required keys exist"
B: "Read configuration in TOML format, raise error on missing fields"
C: "TOML loader with mandatory key checking and type validation"
D: "Verify TOML configuration contains all necessary settings"
E: "Configuration validator: load TOML, assert required entries present"
```

### C04 — YAML Config Merging

```
A: "Merge two YAML config files, environment variables override file values"
B: "Combine base and override YAML configs with env var precedence"
C: "Configuration layering: YAML defaults plus environment overrides"
D: "Load hierarchical YAML settings, let env vars take priority"
E: "Multi-source config merger: base.yaml + overrides.yaml + os.environ"
```

### C05 — HTTP Retry Client

```
A: "GET request with automatic retry on 5xx errors, max 3 attempts"
B: "Resilient HTTP fetch: backoff and retry for server failures"
C: "URL retrieval with exponential backoff on transient HTTP errors"
D: "HTTP client that retries failed requests up to three times"
E: "Fault-tolerant GET request handler with configurable retry logic"
```

### C06 — Paginated API Fetch

```
A: "Paginated API fetch: collect all pages until no next_cursor"
B: "Iterate REST endpoint pages, accumulate results until exhausted"
C: "Cursor-based pagination client for REST APIs"
D: "Collect every page from a paginated JSON endpoint automatically"
E: "Auto-pagination wrapper: follow next links until empty response"
```

### C07 — Moving Average

```
A: "Compute rolling 7-day moving average over time series data"
B: "Calculate sliding window mean with period=7 for sequential values"
C: "Time series smoothing: 7-point rolling arithmetic mean"
D: "Apply moving average filter (window 7) to numeric sequence"
E: "Windowed average computation across temporal data points"
```

### C08 — Z-Score Normalization

```
A: "Z-score normalize a list of numeric values"
B: "Standardize array: subtract mean, divide by standard deviation"
C: "Feature scaling using z-score transformation"
D: "Normalize numbers to zero mean and unit variance"
E: "Statistical standardization of numeric dataset via z-scores"
```

### C09 — Async HTTP Batch

```
A: "Fetch multiple URLs concurrently with asyncio, limit to 5 simultaneous"
B: "Async batch downloader with semaphore-bounded concurrency"
C: "Parallel HTTP requests using asyncio gather with max 5 connections"
D: "Concurrent URL fetching: async event loop with connection limiter"
E: "Non-blocking multi-URL retrieval, cap simultaneous requests at five"
```

### C10 — Regex Email Extraction

```
A: "Extract all email addresses from text using regex"
B: "Find valid emails in a string via regular expression matching"
C: "Regex-based email parser: scan text, return address list"
D: "Pattern matching to extract email addresses from document text"
E: "Email finder: identify and collect addresses using regex patterns"
```

### C11 — PostgreSQL Bulk Upsert

```
A: "Bulk upsert records into PostgreSQL table, skip duplicates on primary key"
B: "Batch INSERT ON CONFLICT DO UPDATE for Postgres table"
C: "PostgreSQL mass upsert: handle key collisions with update strategy"
D: "Efficient bulk write to Postgres with duplicate key resolution"
E: "Database batch operation: insert-or-update rows in PostgreSQL"
```

### C12 — File Deduplication

```
A: "Scan directory recursively and remove duplicate files by MD5 hash"
B: "Find duplicates in folder tree using content-based hashing"
C: "File dedup tool: hash every file, delete copies keeping first"
D: "Directory cleaner: identify and remove duplicate files by checksum"
E: "Recursive file deduplication using MD5 fingerprinting"
```

---

## Noise tasks (15)

Completely unrelated to any cluster.  Expected max similarity to any
cluster pattern should be below the "fresh" threshold.

```
N01: "Resize JPEG image to 800x600 preserving aspect ratio"
N02: "Generate QR code from arbitrary URL string"
N03: "Extract audio waveform peaks from MP3 file"
N04: "Scan nearby Bluetooth devices and list their names"
N05: "Add diagonal watermark text overlay to PDF pages"
N06: "Establish SSH tunnel with local port forwarding"
N07: "Capture video frames at 1 FPS and export as PNG sequence"
N08: "Retrieve current weather forecast from public meteorology API"
N09: "Perform DNS lookup: resolve hostname to IPv4 and IPv6 addresses"
N10: "Generate 4096-bit RSA key pair and save as PEM files"
N11: "Run OCR text extraction on a scanned PNG document"
N12: "Convert HTML table elements into Python list of row dicts"
N13: "Compress entire folder into password-protected ZIP archive"
N14: "Dispatch Slack notification via incoming webhook URL"
N15: "Monitor system CPU usage percentage, alert when exceeding 90%"
```

---

## Boundary tasks (8)

Tasks that straddle two clusters.  Expected: both clusters produce
non-trivial similarity.

```
B01: "Load CSV file, fetch missing values from REST API"          → C01 + C05
B02: "Parse TOML config and validate numeric ranges"              → C03 + C08
B03: "Async batch export CSV rows to cloud storage"               → C09 + C02
B04: "Normalize CSV column values using z-score"                  → C01 + C08
B05: "Retry failed PostgreSQL upsert on deadlock error"           → C11 + C05
B06: "Extract emails from paginated API response"                 → C10 + C06
B07: "Deduplicate files listed in YAML configuration"             → C12 + C04
B08: "Rolling average of async HTTP response latencies"           → C07 + C09
```

---

## Code snippets — quality tiers

Each cluster has 3 code quality levels.  Snippets are used for:
- `/learn` (store the pattern)
- `/evaluate` (test scoring discrimination)

### Tier definitions

| Tier   | eval_score | Characteristics                                     |
|--------|------------|-----------------------------------------------------|
| good   | 8.5-9.5   | Type hints, error handling, docstring, edge cases    |
| medium | 5.5-6.5   | Works for happy path, no error handling, no types    |
| bad    | 2.0-3.5   | Incomplete, wrong logic, syntax issues, no structure |

### Example: C01 — CSV Row Filtering

**Good (eval_score=9.0):**
```python
import csv
from pathlib import Path
from typing import Iterator


def filter_csv_rows(
    path: str | Path,
    column: str,
    value: str,
    *,
    encoding: str = "utf-8",
) -> list[dict[str, str]]:
    """Filter CSV rows where *column* equals *value*.

    Args:
        path: Path to the CSV file.
        column: Column name to filter on.
        value: Required value (case-sensitive).
        encoding: File encoding (default utf-8).

    Returns:
        List of matching row dicts.

    Raises:
        FileNotFoundError: If *path* does not exist.
        KeyError: If *column* is not in the CSV header.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    with file_path.open(encoding=encoding) as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames and column not in reader.fieldnames:
            raise KeyError(f"Column '{column}' not found. Available: {reader.fieldnames}")
        return [row for row in reader if row.get(column) == value]
```

**Medium (eval_score=6.0):**
```python
import csv

def filter_rows(filepath, col, val):
    with open(filepath) as f:
        reader = csv.DictReader(f)
        results = []
        for row in reader:
            if row[col] == val:
                results.append(row)
    return results
```

**Bad (eval_score=2.5):**
```python
def filter(file, col, val):
    f = open(file)
    lines = f.readlines()
    header = lines[0].strip().split(',')
    out = []
    for line in lines[1:]:
        parts = line.split(',')
        # BUG: doesn't handle quoted commas
        # BUG: no strip() on parts
        if parts[header.index(col)] == val:
            out.append(parts)
    return out
```

---

## Snippet catalog — all clusters

Below is the task+code matrix.  Full code is in `tests/recall_quality/snippets/`.

| Cluster | Good snippet | Medium snippet | Bad snippet |
|---------|-------------|----------------|-------------|
| C01 CSV Filter | csv.DictReader + Path + types | csv.DictReader no types | manual split, no quoting |
| C02 CSV Aggregate | pandas groupby + agg | collections.defaultdict | nested loop, O(n*m) |
| C03 TOML Validation | tomllib + Pydantic schema | tomllib + manual checks | regex on TOML text |
| C04 YAML Merge | deep_merge + os.environ | yaml.safe_load + dict.update | yaml.load (unsafe) |
| C05 HTTP Retry | tenacity + requests.Session | urllib + manual loop | requests.get no timeout |
| C06 Pagination | generator + next_cursor | while loop + requests | recursive, no base case |
| C07 Moving Average | numpy convolve | deque sliding window | recompute full sum each step |
| C08 Z-Score | numpy vectorized | manual loop with stats | divides by zero if std=0 |
| C09 Async Batch | asyncio + aiohttp + Semaphore | asyncio.gather unbounded | threading + requests |
| C10 Email Regex | compiled RFC 5322 pattern | r'[\w.]+@[\w.]+' loose | split('@') heuristic |
| C11 PG Upsert | executemany + ON CONFLICT | loop + try/except | string interpolation (SQLi) |
| C12 File Dedup | hashlib.file_digest + pathlib | md5 + os.walk | reads entire file to memory |

---

## Cleanup strategy

Tests create patterns, evals, feedback, skills, and metrics entries.
All must be cleaned up to avoid polluting the shared storage.

### Pattern cleanup
- Every `learn()` is followed by a `recall()` to discover the `pattern_key`.
- All discovered keys are collected in a `Set[str]` fixture.
- Teardown calls `DELETE /patterns/{key}` for each.

### Eval / feedback / metrics cleanup
- These use singleton storage keys (`evals/_list`, `feedback/_list`,
  `metrics/_global`, `skills/_registry`).
- **Local mode:** wipe the JSON files in teardown.
- **Remote mode:** no API exists for cleaning these.  Tests must use a
  **test namespace prefix** (e.g. task descriptions prefixed with
  `[TEST-{uuid}]`) and accept minor pollution.

### Namespace isolation
- All test tasks include a unique run ID: `[RQ-{short_uuid}] actual task text`.
- This serves both cleanup identification and prevents cross-run interference.

---

## Output format

`report.py` produces two artifacts:

### 1. `recall_quality_report.json`
```json
{
  "run_id": "RQ-a1b2c3",
  "timestamp": "2026-03-28T14:30:00Z",
  "mode": "remote",
  "embedding_model": "text-embedding-3-small",
  "calibration": {
    "avg_intra_cluster_sim": 0.72,
    "avg_cross_cluster_sim": 0.31,
    "noise_max_sim": 0.38
  },
  "results": {
    "D1_recall_precision": {"pass": true, "avg_top1_sim": 0.74},
    "D2_cross_cluster": {"pass": true, "max_cross_sim": 0.39},
    "D3_noise_rejection": {"pass": true, "max_noise_sim": 0.38},
    "D4_deduplication": {"pass": true, "dedup_count": 1, "raw_count": 3},
    "D5_reuse_boost": {"pass": true, "score_delta": 1.0, "reuse_count": 10},
    "D6_eval_weighting": {"pass": true, "high_rank": 1, "low_rank": 2},
    "D7_warmup_curve": {"pass": true, "context_lens": [0, 340, 480, 510, 520]},
    "D8_aging": {"pass": true, "pruned": 1, "survived": 1},
    "D9_feedback": {"pass": true, "surfaced": true, "decayed": true},
    "D10_skills": {"pass": true, "all_assertions": 5},
    "D11_metrics": {"pass": true, "runs_delta": 5, "pattern_delta": 5},
    "D12_robustness": {"pass": true, "edge_cases": 7}
  }
}
```

### 2. `similarity_matrix.csv`

12x12 matrix of avg similarity between cluster centroids.  Diagonal
should be high (> 0.6), off-diagonal should be low (< 0.4).

---

## File structure

The suite is split into two directories with different purposes:

| | `tests/recall_quality/` | `tests/test_features/` |
|---|---|---|
| **Measures** | Embedding-space quality (longitudinal) | Correctness of system features |
| **Fails when** | Embedding model / thresholds / matcher changes | Code regressions in Engramia |
| **Writes `results/*.json`** | Yes — one per run | No |

```
tests/recall_quality/          # embedding-quality suite (D1–D3 + boundary)
├── DESIGN.md                  # This file
├── conftest.py                # TestClient, QualityTracker, run_tag, thresholds
├── task_clusters.py           # 12 clusters × 5 variants + 15 noise + 8 boundary
├── thresholds.json            # Calibrated thresholds (output of calibrate.py)
├── results/                   # Timestamped JSON per run (git-ignored)
├── calibrate.py               # Compute thresholds for the active embedding model
├── report.py                  # Show latest results + trend table
├── snippets/                  # c01–c12: good/medium/bad code snippets
├── test_d01_recall_precision.py   # intra-cluster top-1 similarity
├── test_d02_cross_cluster.py      # cross-cluster isolation
├── test_d03_noise_rejection.py    # noise task rejection
└── test_boundary_tasks.py         # tasks straddling two clusters

tests/test_features/           # functional regression suite (D4–D12)
├── conftest.py                # Own client + run_tag (isolated from quality storage)
├── test_deduplication.py      # D4: deduplicate=True/False behavior
├── test_reuse_boost.py        # D5: +0.1/recall accumulation, cap 10.0
├── test_eval_weighting.py     # D6: eval_weighted ordering
├── test_warmup_curve.py       # D7: context length grows with learned patterns
├── test_aging.py              # D8: 0.98^weeks decay, prune < 0.1 (local only)
├── test_feedback.py           # D9: EvalFeedbackStore lifecycle
├── test_skills.py             # D10: register_skills + find_by_skills CRUD
├── test_metrics.py            # D11: metrics.runs delta after learn/recall
└── test_robustness.py         # D12: validation boundary cases
```

---

## Running the suite

```bash
# Quality tests (writes results/*.json)
pytest tests/recall_quality/ --no-cov -q

# Feature tests (regression)
pytest tests/test_features/ --no-cov -q

# Both
pytest tests/recall_quality/ tests/test_features/ --no-cov -q
```

### Remote mode (production API)

```bash
export ENGRAMIA_API_URL=https://api.engramia.dev
export ENGRAMIA_API_KEY=sk-...
export ENGRAMIA_TEST_MODE=remote
pytest tests/recall_quality/ tests/test_features/ --no-cov -q
```

### Calibrating thresholds (after embedding model change)

```bash
python tests/recall_quality/calibrate.py   # rewrites thresholds.json
```

### Viewing results and trends

```bash
python tests/recall_quality/report.py
python tests/recall_quality/report.py --last 10   # last 10 runs
python tests/recall_quality/report.py --last 0    # all runs
```

---

## Longitudinal results

Each run of `tests/recall_quality/` writes:

```
tests/recall_quality/results/{timestamp}_{git_hash}.json
```

Schema:

```json
{
  "run_id": "20260328T125902_6b59f30",
  "timestamp": "2026-03-28T12:59:02.123456+00:00",
  "git_commit": "6b59f30",
  "git_branch": "main",
  "embedding_model": "all-MiniLM-L6-v2",
  "thresholds": {"intra": 0.55, "cross": 0.5, "noise": 0.5},
  "dimensions": {
    "D1_recall_precision": {
      "pass": true,
      "clusters_total": 12, "clusters_passed": 12,
      "avg_top1_sim": 0.740, "min_top1_sim": 0.614,
      "per_cluster": {"C01": {"top1_sim": 0.73, "pass": true}}
    },
    "D2_cross_isolation": {
      "pass": true,
      "pairs_total": 6, "pairs_passed": 6,
      "max_cross_sim": 0.283
    },
    "D3_noise_rejection": {
      "pass": true,
      "noise_total": 15, "noise_failed": 0, "max_noise_sim": 0.330
    },
    "boundary": {
      "pass": true,
      "tasks_total": 8, "matched_either": 8, "matched_both": 1
    }
  }
}
```

`results/` is git-ignored — files do not accumulate in the repo. CI can archive
them to artifacts / S3 if trend tracking across runs is needed.

---

## Interpreting results

### D1 — Recall precision (`avg_top1_sim`)
Average similarity of a held-out 5th variant to the 4 learned variants.
- **Improvement**: stronger embedding model (e.g. `all-mpnet-base-v2`).
- **Regression**: matcher changes or threshold drift.

### D2 — Cross-cluster isolation (`max_cross_sim`)
Maximum cross-cluster similarity when recalling from a foreign cluster.
- `< 0.35` — good separation of semantic domains.
- `> 0.45` — model fails to distinguish adjacent domains.

### D3 — Noise rejection (`max_noise_sim`)
Maximum similarity across all noise queries.
- `< 0.40` — reliable rejection of unrelated queries.

### Boundary tasks (`matched_both`)
Count of boundary tasks where both target clusters were relevant — an
aspirational metric; a richer embedding produces higher values.

---

## Acceptance criteria

| Dimension | Criterion |
|-----------|-----------|
| D1 | All 12 clusters: top-1 sim ≥ `intra_threshold` (default 0.55) |
| D2 | All pairs: max cross sim < `cross_threshold` (default 0.50) |
| D3 | All noise tasks: max sim < `noise_threshold` (default 0.50) |
| Boundary | At least one cluster of each boundary pair relevant |
| D4–D12 | See `tests/test_features/` — functional correctness |

After changing the embedding model or matcher parameters:

1. Run `calibrate.py` → new `thresholds.json`.
2. Run `pytest tests/recall_quality/` → new results file.
3. Run `report.py` → compare against prior runs in the trend table.

---

## Estimated test count

| Dimension | Test functions | Learn calls | Recall calls |
|-----------|---------------|-------------|--------------|
| D1 Precision | 12 (1/cluster) | 60 | 12 |
| D2 Isolation | 6 (cluster pairs) | 0 (reuses D1 data) | 12 |
| D3 Noise | 1 | 0 | 15 |
| D4 Dedup | 2 | 3 | 2 |
| D5 Reuse boost | 2 | 1 | 10 |
| D6 Eval weight | 2 | 2 | 2 |
| D7 Warmup | 1 | 5 | 5 |
| D8 Aging | 4 | 3 | 0 |
| D9 Feedback | 3 | 0 | 0 |
| D10 Skills | 5 | 3 | 0 |
| D11 Metrics | 2 | 5 | 3 |
| D12 Robustness | 8 | 2 | 2 |
| Boundary | 8 | 0 (reuses D1) | 8 |
| **Total** | **~56** | **~84** | **~71** |

---

## Not tested here (intentionally)

- **`/compose` pipeline decomposition** — requires LLM calls; not
  deterministic; better suited for a separate LLM integration test.
- **`/evolve` prompt evolution** — same reason; LLM-dependent output.
- **`/evaluate` scoring** — requires LLM; tested separately in
  `tests/test_eval/`.
- **Rate limiting / auth** — tested in `tests/test_api/test_auth.py`
  and `tests/test_security/`.
- **Concurrent write safety** — tested in `tests/test_json_storage_concurrent.py`.

These are excluded to keep the suite **deterministic and fast**.
LLM-dependent dimensions get their own test suites with `@pytest.mark.llm`.
