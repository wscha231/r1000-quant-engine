# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 25.73% | 7.42% | -18.30% |
| MaxDD | -62.51% | -27.87% | 34.64% |
| Sharpe | 0.783 | 0.520 | -0.263 |
| Avg Cash | 10.11% | 73.68% | 63.57% |

## Base MDD Trade Window

- Window: `2021-02-12` to `2023-10-27`
- Raw executions inside window: `231`
- Gross traded: `$4,433,681`
- Net cash delta from executions: `$1,496`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `157`
- Estimated cash-action cost: `$5,573`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `workflow_default`
- Best CAGR / MaxDD: `7.42%` / `-27.87%`
- Best target pass: `False`
- Best cash actions: `157`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
