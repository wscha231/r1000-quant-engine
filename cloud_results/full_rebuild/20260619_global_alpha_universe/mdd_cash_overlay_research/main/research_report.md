# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 39.56% | 27.44% | -12.12% |
| MaxDD | -24.46% | -23.93% | 0.53% |
| Sharpe | 1.389 | 1.140 | -0.249 |
| Avg Cash | 26.51% | 40.27% | 13.77% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2022-09-26`
- Raw executions inside window: `203`
- Gross traded: `$977,987`
- Net cash delta from executions: `$103,828`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `224`
- Estimated cash-action cost: `$12,631`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `38.56%` / `-24.49%`
- Best target pass: `True`
- Best cash actions: `66`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
