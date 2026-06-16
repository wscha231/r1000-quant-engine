# MDD Cash Overlay Research - main

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 35.01% | 23.27% | -11.73% |
| MaxDD | -26.05% | -23.94% | 2.11% |
| Sharpe | 1.291 | 1.026 | -0.265 |
| Avg Cash | 26.67% | 38.87% | 12.20% |

## Base MDD Trade Window

- Window: `2020-02-19` to `2020-03-18`
- Raw executions inside window: `17`
- Gross traded: `$59,646`
- Net cash delta from executions: `$42,271`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `260`
- Estimated cash-action cost: `$13,747`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_fast_reentry`
- Best CAGR / MaxDD: `32.45%` / `-25.26%`
- Best target pass: `False`
- Best cash actions: `153`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
