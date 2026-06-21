# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.66% | 18.43% | -26.23% |
| MaxDD | -25.86% | -25.12% | 0.74% |
| Sharpe | 1.394 | 0.905 | -0.490 |
| Avg Cash | 42.48% | 65.52% | 23.04% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,643,435`
- Net cash delta from executions: `$-9,539`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `247`
- Estimated cash-action cost: `$11,529`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `39.87%` / `-25.45%`
- Best target pass: `False`
- Best cash actions: `114`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
