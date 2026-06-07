# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 33.46% | 18.69% | -14.76% |
| MaxDD | -26.23% | -24.53% | 1.71% |
| Sharpe | 1.251 | 0.892 | -0.359 |
| Avg Cash | 27.25% | 43.07% | 15.82% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$50,807`
- Net cash delta from executions: `$41,468`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `279`
- Estimated cash-action cost: `$13,022`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `32.45%` / `-26.67%`
- Best target pass: `False`
- Best cash actions: `81`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
