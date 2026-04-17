# ROI Score Calibration Guide

The composite ROI score (0-10) measures how much value Engramia's memory provides.
It is computed by the `/v1/analytics/rollup` endpoint for hourly, daily, or weekly windows.

## Formula

```
ROI = 0.6 × reuse_rate × 10 + 0.4 × avg_eval_score
```

| Component | Weight | Meaning |
|-----------|--------|---------|
| `reuse_rate` | 60% | Fraction of recalls that found a reusable pattern (duplicate + adapt tiers) |
| `avg_eval_score` | 40% | Average quality score of learned patterns |

The reuse component is weighted more heavily because reuse is the primary value
signal — avoiding redundant work is why memory exists.

## Score interpretation

| Score | Label | Meaning | Typical scenario |
|-------|-------|---------|------------------|
| 0-2 | Cold start | Memory is barely useful | Few patterns stored, most recalls return "fresh" |
| 2-4 | Early value | Some patterns are being reused | ~20-30% recall reuse rate, moderate eval scores |
| 4-6 | Productive | Memory is delivering clear value | ~40-60% reuse rate, good eval scores |
| 6-8 | High efficiency | Strong pattern library | >60% reuse rate, consistently high eval scores |
| 8-10 | Optimal | Near-complete coverage | >80% reuse rate, excellent code quality |

## Interpreting the components

### Reuse rate

```
reuse_rate = (duplicate_hits + adapt_hits) / total_recalls
```

- **< 20%**: Memory has poor coverage of the task domain. Need more patterns.
- **20-50%**: Growing coverage. Normal for the first weeks of use.
- **50-80%**: Strong coverage. Most tasks have relevant prior experience.
- **> 80%**: Excellent. The agent rarely encounters truly novel tasks.

### Average eval score

- **< 5.0**: Stored patterns have quality issues. Review evaluation criteria.
- **5.0-7.0**: Acceptable quality. Typical for automated scoring.
- **7.0-9.0**: High quality patterns. Agents produce consistently good code.
- **> 9.0**: Exceptional. May indicate eval scoring is too lenient.

## Improving your ROI score

| Problem | Score symptom | Action |
|---------|--------------|--------|
| Low reuse rate | ROI < 3 despite good eval scores | Learn more patterns; broaden task coverage |
| Low eval scores | ROI < 5 despite decent reuse | Review code quality; tighten eval prompts |
| High variance in evals | Inconsistent scores | Increase `num_evals` (3-5) for more stable median |
| Stale patterns | Declining ROI over time | Run `engramia aging` regularly; patterns decay 2%/week |
| Wrong domain | ROI stuck at 0 | Ensure recalled tasks match the agent's actual workload |

## Percentile metrics

The rollup also includes `p50` (median) and `p90` eval scores:

- **p50** — half of learned patterns score above this. A reliable "typical quality" indicator.
- **p90** — top 10% quality level. Useful for identifying your best patterns.

A large gap between p50 and p90 suggests inconsistent code quality — focus on
raising the floor rather than the ceiling.
