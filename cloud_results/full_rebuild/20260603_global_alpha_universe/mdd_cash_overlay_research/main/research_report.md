# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 27.28% | 16.84% | -10.44% |
| MaxDD | -38.95% | -27.30% | 11.64% |
| Sharpe | 1.031 | 0.875 | -0.156 |
| Avg Cash | 19.27% | 47.31% | 28.04% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2023-10-27`
- Raw executions inside window: `472`
- Gross traded: `$2,815,520`
- Net cash delta from executions: `$36,463`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `234`
- Estimated cash-action cost: `$10,955`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `24.77%` / `-36.24%`
- Best target pass: `False`
- Best cash actions: `83`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
