# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 31.36% | 21.46% | -9.90% |
| MaxDD | -37.45% | -26.63% | 10.82% |
| Sharpe | 1.136 | 0.988 | -0.148 |
| Avg Cash | 19.66% | 41.78% | 22.13% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2023-03-13`
- Raw executions inside window: `328`
- Gross traded: `$1,892,812`
- Net cash delta from executions: `$24,462`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `235`
- Estimated cash-action cost: `$12,129`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `28.85%` / `-35.62%`
- Best target pass: `False`
- Best cash actions: `137`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
