# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.88% | 24.90% | -9.98% |
| MaxDD | -26.05% | -23.55% | 2.49% |
| Sharpe | 1.275 | 1.071 | -0.203 |
| Avg Cash | 26.67% | 39.17% | 12.51% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$49,617`
- Net cash delta from executions: `$39,803`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `236`
- Estimated cash-action cost: `$11,687`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `31.94%` / `-25.33%`
- Best target pass: `False`
- Best cash actions: `160`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
