# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.60% | 18.44% | -26.17% |
| MaxDD | -24.62% | -24.76% | -0.13% |
| Sharpe | 1.395 | 0.907 | -0.489 |
| Avg Cash | 42.43% | 65.54% | 23.11% |

## Base MDD Trade Window

- Window: `2021-11-18` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,640,828`
- Net cash delta from executions: `$-9,536`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `243`
- Estimated cash-action cost: `$11,377`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.38%` / `-24.48%`
- Best target pass: `False`
- Best cash actions: `114`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
