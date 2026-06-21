# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.68% | 22.70% | -11.99% |
| MaxDD | -26.05% | -23.57% | 2.47% |
| Sharpe | 1.269 | 1.001 | -0.268 |
| Avg Cash | 26.66% | 39.97% | 13.31% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$49,637`
- Net cash delta from executions: `$39,823`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `263`
- Estimated cash-action cost: `$13,412`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `31.76%` / `-25.33%`
- Best target pass: `False`
- Best cash actions: `161`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
