# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 35.20% | 22.35% | -12.86% |
| MaxDD | -24.49% | -23.88% | 0.61% |
| Sharpe | 1.305 | 1.004 | -0.301 |
| Avg Cash | 26.58% | 39.57% | 12.98% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2022-09-26`
- Raw executions inside window: `202`
- Gross traded: `$1,089,862`
- Net cash delta from executions: `$117,169`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `268`
- Estimated cash-action cost: `$15,233`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `33.79%` / `-24.78%`
- Best target pass: `False`
- Best cash actions: `81`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
