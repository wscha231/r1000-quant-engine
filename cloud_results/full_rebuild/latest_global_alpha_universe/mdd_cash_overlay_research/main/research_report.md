# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.51% | 22.02% | -12.49% |
| MaxDD | -26.01% | -23.92% | 2.09% |
| Sharpe | 1.275 | 0.984 | -0.290 |
| Avg Cash | 26.61% | 39.24% | 12.63% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$51,388`
- Net cash delta from executions: `$41,470`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `271`
- Estimated cash-action cost: `$14,167`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `33.49%` / `-26.45%`
- Best target pass: `False`
- Best cash actions: `81`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
