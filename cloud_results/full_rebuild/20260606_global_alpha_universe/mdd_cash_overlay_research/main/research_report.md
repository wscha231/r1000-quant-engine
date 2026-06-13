# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 32.69% | 20.78% | -11.91% |
| MaxDD | -28.45% | -25.00% | 3.45% |
| Sharpe | 1.192 | 0.959 | -0.233 |
| Avg Cash | 23.35% | 42.02% | 18.67% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2023-03-13`
- Raw executions inside window: `329`
- Gross traded: `$1,854,641`
- Net cash delta from executions: `$29,418`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `254`
- Estimated cash-action cost: `$13,375`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `31.48%` / `-27.68%`
- Best target pass: `False`
- Best cash actions: `83`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
