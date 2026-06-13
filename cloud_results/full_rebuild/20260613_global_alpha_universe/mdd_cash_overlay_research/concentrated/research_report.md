# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.80% | 16.99% | -27.82% |
| MaxDD | -25.82% | -25.04% | 0.78% |
| Sharpe | 1.405 | 0.856 | -0.549 |
| Avg Cash | 42.32% | 66.15% | 23.83% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,855,686`
- Net cash delta from executions: `$-11,323`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `252`
- Estimated cash-action cost: `$11,928`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.03%` / `-25.37%`
- Best target pass: `False`
- Best cash actions: `114`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
