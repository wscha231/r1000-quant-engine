# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 45.47% | 17.95% | -27.52% |
| MaxDD | -24.59% | -24.68% | -0.10% |
| Sharpe | 1.412 | 0.892 | -0.520 |
| Avg Cash | 41.94% | 65.78% | 23.84% |

## Base MDD Trade Window

- Window: `2021-11-18` to `2023-08-17`
- Raw executions inside window: `142`
- Gross traded: `$1,626,816`
- Net cash delta from executions: `$-9,618`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `250`
- Estimated cash-action cost: `$11,167`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `41.34%` / `-24.53%`
- Best target pass: `False`
- Best cash actions: `113`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
