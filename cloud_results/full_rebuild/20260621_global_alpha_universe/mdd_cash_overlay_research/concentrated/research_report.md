# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.40% | 18.29% | -26.10% |
| MaxDD | -24.70% | -24.52% | 0.18% |
| Sharpe | 1.401 | 0.907 | -0.494 |
| Avg Cash | 41.92% | 65.39% | 23.47% |

## Base MDD Trade Window

- Window: `2021-09-03` to `2023-08-17`
- Raw executions inside window: `156`
- Gross traded: `$1,908,474`
- Net cash delta from executions: `$12,405`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `247`
- Estimated cash-action cost: `$11,332`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.00%` / `-24.56%`
- Best target pass: `False`
- Best cash actions: `116`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
