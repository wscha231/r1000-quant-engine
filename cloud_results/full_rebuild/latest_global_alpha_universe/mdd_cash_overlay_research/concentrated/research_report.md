# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.67% | 15.89% | -28.77% |
| MaxDD | -25.87% | -25.13% | 0.74% |
| Sharpe | 1.394 | 0.817 | -0.578 |
| Avg Cash | 42.48% | 66.11% | 23.63% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,646,025`
- Net cash delta from executions: `$-9,829`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `262`
- Estimated cash-action cost: `$11,501`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `39.85%` / `-25.46%`
- Best target pass: `False`
- Best cash actions: `114`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
