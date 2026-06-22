# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 34.65% | 22.90% | -11.75% |
| MaxDD | -26.00% | -23.54% | 2.46% |
| Sharpe | 1.268 | 1.008 | -0.260 |
| Avg Cash | 26.68% | 39.97% | 13.29% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `16`
- Gross traded: `$49,765`
- Net cash delta from executions: `$39,951`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `260`
- Estimated cash-action cost: `$13,525`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `31.73%` / `-25.30%`
- Best target pass: `False`
- Best cash actions: `161`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
