# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.92% | 21.07% | -13.85% |
| MaxDD | -26.05% | -23.76% | 2.29% |
| Sharpe | 1.273 | 0.965 | -0.308 |
| Avg Cash | 26.35% | 42.69% | 16.34% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$48,256`
- Net cash delta from executions: `$39,287`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `303`
- Estimated cash-action cost: `$14,481`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `32.54%` / `-25.34%`
- Best target pass: `False`
- Best cash actions: `150`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
