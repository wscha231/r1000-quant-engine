# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 44.57% | 15.32% | -29.25% |
| MaxDD | -25.88% | -24.87% | 1.00% |
| Sharpe | 1.401 | 0.803 | -0.599 |
| Avg Cash | 42.37% | 66.45% | 24.08% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `143`
- Gross traded: `$1,846,400`
- Net cash delta from executions: `$-10,667`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `259`
- Estimated cash-action cost: `$12,147`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.22%` / `-25.42%`
- Best target pass: `False`
- Best cash actions: `113`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
