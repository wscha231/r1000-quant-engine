# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 30.61% | 17.11% | -13.50% |
| MaxDD | -26.02% | -23.95% | 2.07% |
| Sharpe | 1.130 | 0.808 | -0.322 |
| Avg Cash | 26.39% | 42.72% | 16.33% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$49,049`
- Net cash delta from executions: `$39,599`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `314`
- Estimated cash-action cost: `$15,614`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `29.67%` / `-26.46%`
- Best target pass: `False`
- Best cash actions: `77`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
