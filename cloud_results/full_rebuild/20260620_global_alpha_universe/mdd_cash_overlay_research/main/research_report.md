# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.73% | 22.68% | -12.05% |
| MaxDD | -26.05% | -23.84% | 2.21% |
| Sharpe | 1.267 | 1.018 | -0.249 |
| Avg Cash | 26.43% | 41.84% | 15.41% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$48,228`
- Net cash delta from executions: `$39,358`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `276`
- Estimated cash-action cost: `$12,867`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `32.24%` / `-25.35%`
- Best target pass: `False`
- Best cash actions: `152`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
