# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 40.61% | 15.99% | -24.62% |
| MaxDD | -29.94% | -24.73% | 5.21% |
| Sharpe | 1.325 | 0.824 | -0.501 |
| Avg Cash | 41.93% | 66.23% | 24.30% |

## Base MDD Trade Window

- Window: `2021-09-03` to `2023-03-15`
- Raw executions inside window: `122`
- Gross traded: `$1,401,036`
- Net cash delta from executions: `$6,230`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `228`
- Estimated cash-action cost: `$10,798`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `35.39%` / `-28.49%`
- Best target pass: `False`
- Best cash actions: `202`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
