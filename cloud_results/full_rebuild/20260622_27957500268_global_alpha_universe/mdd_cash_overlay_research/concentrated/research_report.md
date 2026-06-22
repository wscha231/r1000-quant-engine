# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 45.95% | 18.60% | -27.35% |
| MaxDD | -24.59% | -24.67% | -0.07% |
| Sharpe | 1.434 | 0.922 | -0.512 |
| Avg Cash | 41.32% | 65.53% | 24.21% |

## Base MDD Trade Window

- Window: `2021-11-18` to `2023-08-17`
- Raw executions inside window: `141`
- Gross traded: `$1,616,677`
- Net cash delta from executions: `$-9,891`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `254`
- Estimated cash-action cost: `$11,354`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `41.64%` / `-24.47%`
- Best target pass: `False`
- Best cash actions: `113`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
