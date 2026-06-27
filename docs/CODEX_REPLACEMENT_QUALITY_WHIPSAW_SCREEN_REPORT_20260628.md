# Replacement-Quality Whipsaw Screen Report — 2026-06-28

## Verdict

The replacement-quality whipsaw screen is useful as a diagnostic, but the first
PIT thesis-quality predicate does not justify a policy hook.

Do not run a full rebuild. Do not design a default-OFF hook from this predicate.

## Why This Screen Was Added

The whipsaw audit showed material sell/rebuy drag. A broad
`earnings-confirmed hold` hook then failed broker replay:

- Concentrated CAGR fell from 46.24% to 45.22%
- MaxDD worsened from -25.82% to -27.51%
- Sharpe fell from 1.421 to 1.260

That failure showed that broad hold-duration extension protects too many bad
incumbents. The next hypothesis was narrower:

> Only block replacement when the incumbent's PIT thesis quality is stronger
> than the challenger being added.

## Implementation

New measurement-only tool:

- `tools/run_replacement_quality_whipsaw_screen.py`

Smoke:

- `tests/replacement_quality_whipsaw_screen_smoke.py`

Validation:

- `python tools/run_pr_validation.py --only replacement_quality_whipsaw_screen`

The tool reads:

- Concentrated target book
- Candidate replay book

It compares dropped prior holdings with newly added challengers by rebalance
date. It uses PIT columns only for screening:

- relative strength 3M/6M
- leader tier, with benchmark-RS fallback when native leader tier is missing
- actual results score
- revision score
- sector/industry leadership
- MA50/MA200 trend
- overextension penalty

`period_forward_return` is copied only as an audit label. It is not used for
candidate selection or ranking.

## Clean 7Y Artifact Result

Artifact:

- `artifacts/28074476465/outputs`

Command:

```bash
python tools/run_replacement_quality_whipsaw_screen.py \
  --latest-run artifacts/28074476465/outputs \
  --output-dir artifacts/28074476465/replacement_quality_whipsaw_screen_20260628 \
  --quality-margin 0.20 \
  --min-events 8 \
  --min-positive-rate 0.55 \
  --min-mean-forward-edge 0.0
```

Result:

| Metric | Value |
|---|---:|
| Replacement events | 181 |
| Evaluated pairs | 173 |
| Screen candidates | 7 |
| Positive forward-edge rate | 42.86% |
| Mean forward edge | -5.75% |
| Median forward edge | -5.50% |
| Verdict | `reject_or_inconclusive` |

Margin sensitivity:

| Quality margin | Candidate count | Positive rate | Mean forward edge |
|---:|---:|---:|---:|
| 0.25 | 2 | 0.00% | -33.89% |
| 0.20 | 7 | 42.86% | -5.75% |
| 0.15 | 11 | 36.36% | -7.73% |
| 0.10 | 18 | 27.78% | -11.42% |
| 0.05 | 30 | 23.33% | -12.46% |
| 0.00 | 42 | 26.19% | -11.49% |
| -0.05 | 58 | 31.03% | -8.11% |

Interpretation:

- The PIT quality predicate does not separate good incumbent saves from bad
  incumbent saves.
- Loosening the predicate makes the result worse, not better.
- This should be treated as a rejected candidate, not as a hook waiting for
  broker replay.

## Decision

Keep the screen as a guardrail and diagnostic.

Do not create:

- broad hold-extension hook
- replacement-quality hold hook from this predicate
- fullrun for this candidate

## Next Direction

The whipsaw problem is still real, but this candidate did not solve it.

Next work should shift from "protect incumbent" to "avoid bad re-entry timing":

1. Identify names sold and later repurchased much higher.
2. At the first re-entry date, test whether the system is buying after
   overextension.
3. Compare an earlier re-entry trigger versus the current re-entry trigger.
4. Accept only if broker-ledger CAGR improves and MDD does not worsen.

That next candidate targets the second half of the whipsaw:

- not just "do not sell"
- but "if sold, do not wait until the leader is already much more expensive"

Production promotion remains blocked while `pit_universe_label_clean=false`.
