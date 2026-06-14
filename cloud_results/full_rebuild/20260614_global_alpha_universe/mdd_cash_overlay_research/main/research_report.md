# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.33% | 19.99% | -14.34% |
| MaxDD | -25.93% | -23.89% | 2.05% |
| Sharpe | 1.271 | 0.938 | -0.333 |
| Avg Cash | 26.79% | 42.27% | 15.48% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `17`
- Gross traded: `$57,827`
- Net cash delta from executions: `$41,345`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `312`
- Estimated cash-action cost: `$15,402`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `33.26%` / `-26.36%`
- Best target pass: `False`
- Best cash actions: `80`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
