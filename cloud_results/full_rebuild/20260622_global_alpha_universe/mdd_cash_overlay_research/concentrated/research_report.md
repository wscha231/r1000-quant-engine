# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 45.06% | 19.39% | -25.68% |
| MaxDD | -26.05% | -24.36% | 1.69% |
| Sharpe | 1.399 | 0.938 | -0.461 |
| Avg Cash | 41.22% | 65.28% | 24.06% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `142`
- Gross traded: `$1,809,971`
- Net cash delta from executions: `$-9,899`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `242`
- Estimated cash-action cost: `$11,764`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.72%` / `-25.93%`
- Best target pass: `False`
- Best cash actions: `111`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
