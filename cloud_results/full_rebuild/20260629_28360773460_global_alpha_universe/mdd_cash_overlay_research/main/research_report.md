# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 35.28% | 24.90% | -10.38% |
| MaxDD | -24.25% | -23.59% | 0.66% |
| Sharpe | 1.268 | 1.044 | -0.224 |
| Avg Cash | 26.54% | 38.40% | 11.85% |

## Base MDD Trade Window

- Window: `2025-02-18` to `2025-04-04`
- Raw executions inside window: `44`
- Gross traded: `$568,645`
- Net cash delta from executions: `$125,808`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `237`
- Estimated cash-action cost: `$13,397`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `balanced_lite_dd`
- Best CAGR / MaxDD: `33.58%` / `-24.15%`
- Best target pass: `True`
- Best cash actions: `123`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
