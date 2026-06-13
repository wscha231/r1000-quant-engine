# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.86% | 17.02% | -27.85% |
| MaxDD | -25.83% | -24.92% | 0.91% |
| Sharpe | 1.406 | 0.856 | -0.550 |
| Avg Cash | 42.31% | 66.07% | 23.76% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `142`
- Gross traded: `$1,862,213`
- Net cash delta from executions: `$-10,942`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `253`
- Estimated cash-action cost: `$11,942`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.01%` / `-25.39%`
- Best target pass: `False`
- Best cash actions: `116`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
