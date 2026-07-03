# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.53% | 16.42% | -28.11% |
| MaxDD | -23.27% | -24.40% | -1.13% |
| Sharpe | 1.354 | 0.798 | -0.556 |
| Avg Cash | 41.54% | 64.97% | 23.42% |

## Base MDD Trade Window

- Window: `2025-02-18` to `2025-04-08`
- Raw executions inside window: `16`
- Gross traded: `$466,433`
- Net cash delta from executions: `$166,529`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `263`
- Estimated cash-action cost: `$13,506`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.56%` / `-24.23%`
- Best target pass: `False`
- Best cash actions: `117`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
