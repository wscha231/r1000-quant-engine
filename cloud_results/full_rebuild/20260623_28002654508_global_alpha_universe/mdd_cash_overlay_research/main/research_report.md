# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 35.02% | 21.03% | -13.99% |
| MaxDD | -26.03% | -23.75% | 2.28% |
| Sharpe | 1.276 | 0.965 | -0.311 |
| Avg Cash | 26.36% | 42.79% | 16.43% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$48,275`
- Net cash delta from executions: `$39,405`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `304`
- Estimated cash-action cost: `$14,410`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `32.63%` / `-25.34%`
- Best target pass: `False`
- Best cash actions: `151`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
