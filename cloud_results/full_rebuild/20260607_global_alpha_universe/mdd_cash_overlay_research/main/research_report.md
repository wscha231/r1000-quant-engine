# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 32.38% | 20.77% | -11.61% |
| MaxDD | -28.45% | -25.01% | 3.43% |
| Sharpe | 1.183 | 0.959 | -0.224 |
| Avg Cash | 23.36% | 41.95% | 18.59% |

## Base MDD Trade Window

- Window: `2021-11-19` to `2023-03-13`
- Raw executions inside window: `328`
- Gross traded: `$1,826,220`
- Net cash delta from executions: `$28,054`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `257`
- Estimated cash-action cost: `$13,497`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `31.28%` / `-27.69%`
- Best target pass: `False`
- Best cash actions: `81`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
