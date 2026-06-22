# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.35% | 18.31% | -26.05% |
| MaxDD | -24.70% | -24.76% | -0.06% |
| Sharpe | 1.400 | 0.908 | -0.492 |
| Avg Cash | 41.94% | 65.40% | 23.46% |

## Base MDD Trade Window

- Window: `2021-09-03` to `2023-08-17`
- Raw executions inside window: `156`
- Gross traded: `$1,905,920`
- Net cash delta from executions: `$12,215`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `244`
- Estimated cash-action cost: `$11,236`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `39.86%` / `-24.65%`
- Best target pass: `False`
- Best cash actions: `114`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
