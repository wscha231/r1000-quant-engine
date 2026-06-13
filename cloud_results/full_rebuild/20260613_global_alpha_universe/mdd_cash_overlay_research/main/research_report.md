# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.63% | 24.11% | -10.52% |
| MaxDD | -26.01% | -23.95% | 2.06% |
| Sharpe | 1.278 | 1.051 | -0.227 |
| Avg Cash | 26.61% | 38.43% | 11.83% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$51,388`
- Net cash delta from executions: `$41,470`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `234`
- Estimated cash-action cost: `$11,937`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `33.51%` / `-26.45%`
- Best target pass: `False`
- Best cash actions: `82`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
