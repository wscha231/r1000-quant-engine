# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.43% | 18.66% | -25.77% |
| MaxDD | -25.92% | -25.06% | 0.86% |
| Sharpe | 1.402 | 0.920 | -0.483 |
| Avg Cash | 42.57% | 65.67% | 23.10% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,928,510`
- Net cash delta from executions: `$-11,351`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `247`
- Estimated cash-action cost: `$12,799`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `39.70%` / `-25.47%`
- Best target pass: `False`
- Best cash actions: `116`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
