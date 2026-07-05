# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 46.99% | 24.56% | -22.42% |
| MaxDD | -23.22% | -20.30% | 2.93% |
| Sharpe | 1.455 | 1.048 | -0.407 |
| Avg Cash | 41.04% | 56.63% | 15.59% |

## Base MDD Trade Window

- Window: `2025-02-18` to `2025-04-08`
- Raw executions inside window: `19`
- Gross traded: `$550,756`
- Net cash delta from executions: `$204,460`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `301`
- Estimated cash-action cost: `$19,987`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `43.92%` / `-23.52%`
- Best target pass: `False`
- Best cash actions: `110`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
