# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 45.96% | 18.62% | -27.34% |
| MaxDD | -24.60% | -24.67% | -0.07% |
| Sharpe | 1.434 | 0.923 | -0.511 |
| Avg Cash | 41.33% | 65.45% | 24.12% |

## Base MDD Trade Window

- Window: `2021-11-18` to `2023-08-17`
- Raw executions inside window: `141`
- Gross traded: `$1,616,136`
- Net cash delta from executions: `$-9,677`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `256`
- Estimated cash-action cost: `$11,462`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `41.67%` / `-24.50%`
- Best target pass: `False`
- Best cash actions: `113`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
