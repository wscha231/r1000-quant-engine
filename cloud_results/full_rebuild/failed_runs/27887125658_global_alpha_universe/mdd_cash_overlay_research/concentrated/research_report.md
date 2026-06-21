# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.37% | 18.28% | -26.09% |
| MaxDD | -24.70% | -24.52% | 0.18% |
| Sharpe | 1.399 | 0.906 | -0.494 |
| Avg Cash | 41.88% | 65.42% | 23.54% |

## Base MDD Trade Window

- Window: `2021-09-03` to `2023-08-17`
- Raw executions inside window: `155`
- Gross traded: `$1,906,100`
- Net cash delta from executions: `$12,254`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `247`
- Estimated cash-action cost: `$11,301`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.00%` / `-24.59%`
- Best target pass: `False`
- Best cash actions: `115`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
