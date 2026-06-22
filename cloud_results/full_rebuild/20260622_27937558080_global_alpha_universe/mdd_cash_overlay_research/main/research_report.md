# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.71% | 20.97% | -13.74% |
| MaxDD | -26.03% | -23.62% | 2.41% |
| Sharpe | 1.269 | 0.964 | -0.305 |
| Avg Cash | 26.59% | 42.92% | 16.33% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$49,623`
- Net cash delta from executions: `$39,809`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `305`
- Estimated cash-action cost: `$14,821`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `31.91%` / `-25.31%`
- Best target pass: `False`
- Best cash actions: `158`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
