# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 26.87% | 4.94% | -21.94% |
| MaxDD | -48.02% | -25.69% | 22.33% |
| Sharpe | 0.898 | 0.373 | -0.525 |
| Avg Cash | 29.79% | 71.58% | 41.79% |

## Base MDD Trade Window

- Window: `2021-02-09` to `2023-08-17`
- Raw executions inside window: `216`
- Gross traded: `$3,515,665`
- Net cash delta from executions: `$-59,877`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `192`
- Estimated cash-action cost: `$6,298`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `crisis_only_confirm2`
- Best CAGR / MaxDD: `22.95%` / `-44.67%`
- Best target pass: `False`
- Best cash actions: `176`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
