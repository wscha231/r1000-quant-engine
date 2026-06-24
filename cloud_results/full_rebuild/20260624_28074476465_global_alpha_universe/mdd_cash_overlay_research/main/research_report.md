# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 33.15% | 19.46% | -13.69% |
| MaxDD | -26.02% | -23.72% | 2.30% |
| Sharpe | 1.219 | 0.901 | -0.318 |
| Avg Cash | 26.70% | 42.62% | 15.92% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$48,869`
- Net cash delta from executions: `$39,634`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `307`
- Estimated cash-action cost: `$14,615`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `30.68%` / `-25.32%`
- Best target pass: `False`
- Best cash actions: `157`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
