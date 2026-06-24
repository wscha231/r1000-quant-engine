# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 46.24% | 18.46% | -27.78% |
| MaxDD | -25.82% | -25.02% | 0.80% |
| Sharpe | 1.421 | 0.902 | -0.519 |
| Avg Cash | 42.18% | 65.83% | 23.65% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,856,124`
- Net cash delta from executions: `$-10,884`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `261`
- Estimated cash-action cost: `$13,149`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `41.40%` / `-25.39%`
- Best target pass: `False`
- Best cash actions: `116`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
