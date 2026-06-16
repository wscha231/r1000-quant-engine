# MDD Cash Overlay Research - concentrated

Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.

| Metric | Base broker replay | Cash overlay | Delta |
| --- | ---: | ---: | ---: |
| CAGR | 45.00% | 18.07% | -26.93% |
| MaxDD | -25.82% | -25.03% | 0.79% |
| Sharpe | 1.411 | 0.904 | -0.507 |
| Avg Cash | 42.29% | 65.94% | 23.65% |

## Base MDD Trade Window

- Window: `2021-11-08` to `2023-08-17`
- Raw executions inside window: `142`
- Gross traded: `$1,860,332`
- Net cash delta from executions: `$-11,191`

## Cash Overlay

- Crisis state source: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/alphaops_vnext/daily_crisis_state.csv`
- Cash actions: `256`
- Estimated cash-action cost: `$12,607`
- Confirm days: `2`
- Release step: `10.00%`

## Variant Sweep

- Best variant: `late_dd_fast_release`
- Best CAGR / MaxDD: `40.02%` / `-25.37%`
- Best target pass: `False`
- Best cash actions: `115`

Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.
